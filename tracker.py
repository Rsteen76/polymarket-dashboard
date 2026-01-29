#!/usr/bin/env python3
"""
Polymarket Whale Tracker

Monitors whale wallets on Polymarket, logs their trades, tracks outcomes,
and sends Telegram alerts for significant moves.
"""

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

from database import Database
from polymarket_api import PolymarketAPI
from alerts import TelegramAlerts
from resolution_checker import ResolutionChecker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('tracker.log')
    ]
)
logger = logging.getLogger(__name__)


class WhaleTracker:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.db = Database(self.config.get("database_path", "whales.db"))
        self.api = PolymarketAPI()
        self.alerts = TelegramAlerts(
            self.config.get("telegram_bot_token", ""),
            self.config.get("telegram_chat_id", "")
        )
        self.resolution_checker = ResolutionChecker(self.config.get("database_path", "whales.db"))
        self.running = False
        self._setup_signal_handlers()

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return {
                "poll_interval_seconds": 60,
                "min_position_size": 5000,
                "min_whale_volume": 50000,
                "database_path": "whales.db"
            }

        with open(path, 'r') as f:
            config = json.load(f)
            logger.info(f"Loaded config from {config_path}")
            return config

    def _setup_signal_handlers(self):
        """Setup graceful shutdown handlers."""
        def signal_handler(sig, frame):
            logger.info("Shutdown signal received, stopping...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def discover_whales(self):
        """Discover and add new whales to tracking."""
        logger.info("Starting whale discovery...")
        min_volume = self.config.get("min_whale_volume", 50000)

        try:
            whales = await self.api.discover_whales(min_volume=min_volume, limit=50)
            new_count = 0

            for whale in whales:
                address = whale['address']
                volume = whale['total_volume']

                if self.db.add_whale(address, volume):
                    new_count += 1
                    logger.info(f"New whale added: {address[:10]}... (${volume:,.0f})")
                    await self.alerts.send_whale_discovery_alert(address, volume)
                else:
                    # Update volume for existing whale
                    self.db.update_whale_volume(address, volume)

            logger.info(f"Whale discovery complete: {new_count} new, {len(whales)} total found")
            return whales

        except Exception as e:
            logger.error(f"Error during whale discovery: {e}")
            return []

    async def check_whale_positions(self, whale_address: str):
        """Check for new significant positions for a whale."""
        min_size = self.config.get("min_position_size", 5000)

        try:
            positions = await self.api.get_active_positions_for_wallet(whale_address, min_size)

            for pos in positions:
                market_id = pos['market_id']
                if not market_id:
                    continue

                # Check if we already logged this position
                if self.db.trade_exists(whale_address, market_id, pos['side']):
                    continue

                # New position found
                logger.info(f"New position: {whale_address[:10]}... - {pos['side']} ${pos['size']:,.0f}")

                # Add market if not exists
                self.db.add_market(market_id, pos['market_question'])

                # Log the trade
                trade_id = self.db.add_trade(
                    whale_address=whale_address,
                    market_id=market_id,
                    market_question=pos['market_question'],
                    side=pos['side'],
                    size=pos['size'],
                    entry_price=pos['entry_price']
                )

                if trade_id > 0:
                    # Get whale stats for alert
                    wins, losses, _ = self.db.get_whale_win_rate(whale_address)

                    # Send alert
                    await self.alerts.send_whale_alert(
                        wallet=whale_address,
                        market_question=pos['market_question'],
                        side=pos['side'],
                        size=pos['size'],
                        win_count=wins,
                        loss_count=losses
                    )

        except Exception as e:
            logger.error(f"Error checking positions for {whale_address[:10]}...: {e}")

    async def check_market_resolutions(self):
        """Check if any tracked markets have resolved using ResolutionChecker."""
        try:
            # Use the dedicated resolution checker for better API handling
            summary = await self.resolution_checker.check_all_unresolved(verbose=False)
            
            if summary['markets_resolved'] > 0:
                logger.info(f"Resolved {summary['markets_resolved']} markets, "
                          f"{summary['total_trades_resolved']} trades "
                          f"({summary['total_wins']}W-{summary['total_losses']}L)")
                
                # Send alerts for each resolution
                for res in summary.get('resolutions', []):
                    await self.alerts.send_resolution_alert(
                        market_question=res['question'],
                        resolution=res['winner'],
                        winning_whales=[],  # Could track this in ResolutionChecker if needed
                        losing_whales=[]
                    )
        except Exception as e:
            logger.error(f"Error in resolution check: {e}")

    async def check_new_markets(self):
        """Check for new markets - SNIPE OPPORTUNITIES."""
        try:
            markets = await self.api.get_new_markets(limit=200)
            new_count = 0

            for market in markets:
                condition_id = market.get('conditionId') or market.get('condition_id')
                if not condition_id:
                    continue

                # Check if we've seen this market
                if self.db.is_market_seen(condition_id):
                    continue

                # New market found!
                question = market.get('question', 'Unknown')
                slug = market.get('slug', '')
                volume = float(market.get('volume', 0) or 0)
                liquidity = float(market.get('liquidity', 0) or 0)
                
                # Get initial prices
                yes_price = None
                no_price = None
                try:
                    outcome_prices = market.get('outcomePrices', [])
                    if outcome_prices and len(outcome_prices) >= 2:
                        yes_price = float(outcome_prices[0])
                        no_price = float(outcome_prices[1])
                except:
                    pass

                # Add to seen markets with prices
                self.db.add_seen_market(condition_id, slug, question, volume, liquidity,
                                       yes_price, no_price)
                new_count += 1

                logger.info(f"🚨 NEW MARKET: {question[:50]}... (YES @ ${yes_price:.2f})" if yes_price else f"🚨 NEW MARKET: {question[:50]}...")

                # Alert for new market
                await self.alerts.send_new_market_alert(
                    question=question,
                    slug=slug,
                    volume=volume,
                    liquidity=liquidity,
                    yes_price=yes_price
                )

                await asyncio.sleep(0.3)  # Rate limiting on alerts

            if new_count > 0:
                logger.info(f"Found {new_count} new markets")

        except Exception as e:
            logger.error(f"Error checking new markets: {e}")

    async def check_market_price_updates(self):
        """Check price changes for tracked new markets (1hr, 24hr, 7d)."""
        try:
            # Check 1hr markets
            markets_1hr = self.db.get_markets_needing_check("1hr")
            for market in markets_1hr[:10]:  # Limit to avoid rate limits
                prices = await self.api.get_market_prices(market['condition_id'])
                if prices.get('yes_price'):
                    self.db.update_market_price(market['condition_id'], "1hr", prices['yes_price'])
                    
                    # Calculate gain
                    initial = market.get('initial_yes_price', 0)
                    current = prices['yes_price']
                    if initial and initial > 0:
                        gain_pct = (current - initial) / initial * 100
                        if abs(gain_pct) > 20:  # Alert on significant moves
                            await self.alerts.send_price_update_alert(
                                market['question'], "1hr", initial, current, gain_pct
                            )
                await asyncio.sleep(0.2)
            
            # Check 24hr markets
            markets_24hr = self.db.get_markets_needing_check("24hr")
            for market in markets_24hr[:10]:
                prices = await self.api.get_market_prices(market['condition_id'])
                if prices.get('yes_price'):
                    self.db.update_market_price(market['condition_id'], "24hr", prices['yes_price'])
                await asyncio.sleep(0.2)

        except Exception as e:
            logger.error(f"Error checking market price updates: {e}")

    async def monitoring_loop(self):
        """Main monitoring loop."""
        poll_interval = self.config.get("poll_interval_seconds", 60)

        # Initial market scan - populate seen markets
        logger.info("Scanning existing markets...")
        markets = await self.api.get_new_markets(limit=500)
        for market in markets:
            condition_id = market.get('conditionId') or market.get('condition_id')
            if condition_id:
                slug = market.get('slug', '')
                question = market.get('question', '')
                volume = float(market.get('volume', 0) or 0)
                liquidity = float(market.get('liquidity', 0) or 0)
                self.db.add_seen_market(condition_id, slug, question, volume, liquidity)
        logger.info(f"Indexed {self.db.get_seen_market_count()} existing markets")

        # Send startup alert
        whales = self.db.get_all_whales()
        unresolved_trades = self.db.get_unresolved_trades()
        await self.alerts.send_startup_alert(len(whales), len(unresolved_trades))

        logger.info(f"Starting monitoring loop (interval: {poll_interval}s)")
        logger.info(f"Tracking {len(whales)} whales, {len(unresolved_trades)} open trades")

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1
                logger.info(f"=== Monitoring cycle {cycle_count} ===")

                # Get all tracked whales
                whales = self.db.get_all_whales()

                # Check each whale's positions
                for whale in whales:
                    await self.check_whale_positions(whale['address'])
                    await asyncio.sleep(0.5)  # Rate limiting

                # Check for market resolutions
                await self.check_market_resolutions()

                # Check for NEW markets (snipe opportunities!)
                await self.check_new_markets()

                # Check price updates for tracked new markets (every 5 cycles)
                if cycle_count % 5 == 0:
                    await self.check_market_price_updates()

                # Periodic whale discovery (every 10 cycles)
                if cycle_count % 10 == 0:
                    await self.discover_whales()

                # Log stats
                unresolved = self.db.get_unresolved_trades()
                seen_markets = self.db.get_seen_market_count()
                logger.info(f"Cycle {cycle_count} complete. Open trades: {len(unresolved)}, Markets indexed: {seen_markets}")

                # Wait for next cycle
                await asyncio.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await self.alerts.send_error_alert(str(e))
                await asyncio.sleep(poll_interval)

    async def run(self):
        """Run the whale tracker."""
        logger.info("="*50)
        logger.info("Polymarket Whale Tracker Starting")
        logger.info("="*50)

        self.running = True

        try:
            # Initial whale discovery if database is empty
            whales = self.db.get_all_whales()
            if not whales:
                logger.info("No whales in database, running initial discovery...")
                await self.discover_whales()
            else:
                logger.info(f"Found {len(whales)} whales in database")

            # Start monitoring loop
            await self.monitoring_loop()

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            await self.alerts.send_error_alert(f"Fatal error: {e}")
            raise
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down...")
        self.running = False
        await self.api.close()
        await self.alerts.close()
        await self.resolution_checker.close()
        self.db.close()
        logger.info("Shutdown complete")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Polymarket Whale Tracker")
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to config file (default: config.json)"
    )
    parser.add_argument(
        "-d", "--discover",
        action="store_true",
        help="Run whale discovery only, then exit"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Fix for Windows ProactorEventLoop issues
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    tracker = WhaleTracker(args.config)

    async def run_discovery():
        """Run discovery mode in a single event loop."""
        try:
            await tracker.discover_whales()
        finally:
            await tracker.shutdown()

    if args.discover:
        # Discovery mode only - run in single event loop
        asyncio.run(run_discovery())
    else:
        # Full tracking mode
        asyncio.run(tracker.run())


if __name__ == "__main__":
    main()
