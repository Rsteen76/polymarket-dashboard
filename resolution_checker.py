#!/usr/bin/env python3
"""
Market Resolution Checker

Checks tracked markets for resolution and updates trades/whale stats.
Can be run standalone or imported by tracker.py.
"""

import asyncio
import aiohttp
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"


class ResolutionChecker:
    def __init__(self, db_path: str = "whales.db"):
        self.db_path = db_path
        self.session = None
        
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"Accept": "application/json"}
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _get_db_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_unresolved_market_ids(self) -> List[str]:
        """Get unique market IDs from unresolved trades (only valid hex IDs)."""
        conn = self._get_db_connection()
        c = conn.cursor()
        # Only get hex condition IDs (start with 0x), skip test data
        c.execute("""
            SELECT DISTINCT market_id FROM trades 
            WHERE (resolved = 0 OR resolved IS NULL)
            AND market_id LIKE '0x%'
        """)
        ids = [r[0] for r in c.fetchall()]
        conn.close()
        logger.info(f"Found {len(ids)} unresolved markets with valid hex IDs")
        return ids
    
    async def check_market_resolution(self, market_id: str) -> Optional[Dict]:
        """
        Check if a market has resolved via CLOB API.
        Returns dict with resolution info or None if not resolved/error.
        """
        await self._ensure_session()
        
        # Use CLOB API - returns correct market data for condition_id
        url = f"{CLOB_API_BASE}/markets/{market_id}"
        
        try:
            async with self.session.get(url, timeout=15) as resp:
                if resp.status == 404:
                    # Market not found in CLOB - might be old/delisted
                    return None
                if resp.status != 200:
                    return None
                    
                data = await resp.json()
                if not data:
                    return None
                
                # Check if market is closed
                closed = data.get('closed', False)
                if not closed:
                    return None
                
                # Check tokens for winner
                tokens = data.get('tokens', [])
                winner = None
                for token in tokens:
                    if token.get('winner', False):
                        outcome = token.get('outcome', '').upper()
                        if outcome in ('YES', 'NO'):
                            winner = outcome
                            break
                
                # If no explicit winner but closed, check prices
                if not winner and tokens:
                    for token in tokens:
                        price = float(token.get('price', 0))
                        outcome = token.get('outcome', '').upper()
                        # Price of 1.0 (or very close) indicates winner
                        if price > 0.99 and outcome in ('YES', 'NO'):
                            winner = outcome
                            break
                
                if winner:
                    return {
                        "market_id": market_id,
                        "question": data.get('question', 'Unknown'),
                        "winner": winner,
                        "resolved_at": datetime.utcnow().isoformat()
                    }
                
                return None
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout checking market {market_id[:20]}...")
            return None
        except Exception as e:
            logger.error(f"Error checking market {market_id[:20]}...: {e}")
            return None
    
    def resolve_market_trades(self, market_id: str, winner: str) -> Dict:
        """
        Resolve all trades for a market.
        Returns dict with counts of wins/losses and affected whales.
        """
        conn = self._get_db_connection()
        c = conn.cursor()
        
        # Get all unresolved trades for this market
        c.execute("""
            SELECT id, whale_address, side, size, entry_price 
            FROM trades 
            WHERE market_id = ? AND (resolved = 0 OR resolved IS NULL)
        """, (market_id,))
        trades = c.fetchall()
        
        results = {
            "trades_resolved": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "whale_updates": {}  # whale_address -> {wins, losses, pnl}
        }
        
        for trade in trades:
            trade_id = trade['id']
            whale = trade['whale_address']
            side = (trade['side'] or '').upper()
            size = float(trade['size'] or 0)
            entry_price = float(trade['entry_price'] or 0.5)
            
            # Determine if whale won
            won = (side == winner)
            outcome = "WIN" if won else "LOSS"
            
            # Calculate PnL
            # If won: profit = shares * (1 - entry_price) where shares = size/entry_price
            # If lost: loss = -size (what was paid)
            if won:
                # Simplified: profit = size * (1 - entry_price) / entry_price
                # But actually on Polymarket, if you bet $100 at 0.60, you get $100/0.60 = 166 shares
                # If you win, each share pays $1, so profit = 166 - 100 = $66
                shares = size / entry_price if entry_price > 0 else 0
                pnl = shares - size  # net profit
            else:
                pnl = -size  # lost entire stake
            
            # Update trade
            c.execute("""
                UPDATE trades 
                SET resolved = 1, outcome = ?, pnl = ?
                WHERE id = ?
            """, (outcome, pnl, trade_id))
            
            results["trades_resolved"] += 1
            results["total_pnl"] += pnl
            if won:
                results["wins"] += 1
            else:
                results["losses"] += 1
            
            # Track per-whale updates
            if whale not in results["whale_updates"]:
                results["whale_updates"][whale] = {"wins": 0, "losses": 0, "pnl": 0.0}
            
            if won:
                results["whale_updates"][whale]["wins"] += 1
            else:
                results["whale_updates"][whale]["losses"] += 1
            results["whale_updates"][whale]["pnl"] += pnl
        
        # Update whale stats
        for whale, stats in results["whale_updates"].items():
            # Get current stats
            c.execute("SELECT win_count, loss_count FROM whales WHERE address = ?", (whale,))
            row = c.fetchone()
            if row:
                new_wins = (row['win_count'] or 0) + stats["wins"]
                new_losses = (row['loss_count'] or 0) + stats["losses"]
                c.execute("""
                    UPDATE whales SET win_count = ?, loss_count = ? WHERE address = ?
                """, (new_wins, new_losses, whale))
        
        # Mark market as resolved
        c.execute("""
            UPDATE markets SET resolved = 1, resolution = ?, resolved_at = ?
            WHERE market_id = ?
        """, (winner, datetime.utcnow(), market_id))
        
        conn.commit()
        conn.close()
        
        return results
    
    async def check_all_unresolved(self, verbose: bool = True) -> Dict:
        """
        Check all unresolved markets and update database.
        Returns summary of all resolutions.
        """
        market_ids = self.get_unresolved_market_ids()
        
        if verbose:
            logger.info(f"Checking {len(market_ids)} unresolved markets...")
        
        summary = {
            "markets_checked": len(market_ids),
            "markets_resolved": 0,
            "total_trades_resolved": 0,
            "total_wins": 0,
            "total_losses": 0,
            "total_pnl": 0.0,
            "resolutions": []
        }
        
        for i, market_id in enumerate(market_ids):
            resolution = await self.check_market_resolution(market_id)
            
            if resolution:
                logger.info(f"✅ RESOLVED: {resolution['question'][:50]}... -> {resolution['winner']}")
                
                # Resolve trades for this market
                result = self.resolve_market_trades(market_id, resolution["winner"])
                
                summary["markets_resolved"] += 1
                summary["total_trades_resolved"] += result["trades_resolved"]
                summary["total_wins"] += result["wins"]
                summary["total_losses"] += result["losses"]
                summary["total_pnl"] += result["total_pnl"]
                summary["resolutions"].append({
                    "question": resolution["question"],
                    "winner": resolution["winner"],
                    "trades": result["trades_resolved"],
                    "pnl": result["total_pnl"]
                })
            
            # Progress logging every 100 markets
            if (i + 1) % 100 == 0:
                pct = 100 * (i + 1) / len(market_ids)
                logger.info(f"📊 Progress: {i+1}/{len(market_ids)} ({pct:.1f}%) - Found {summary['markets_resolved']} resolved")
                # Write progress file for external monitoring
                try:
                    import json
                    progress = {
                        "checked": i + 1,
                        "total": len(market_ids),
                        "pct": pct,
                        "resolved": summary["markets_resolved"],
                        "trades_resolved": summary["total_trades_resolved"],
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    progress_path = self.db_path.replace("whales.db", "backfill_progress.json")
                    with open(progress_path, "w") as f:
                        json.dump(progress, f)
                except Exception:
                    pass
            
            # Rate limit
            if (i + 1) % 10 == 0:
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(0.3)
        
        if verbose:
            logger.info(f"Resolution check complete:")
            logger.info(f"  Markets resolved: {summary['markets_resolved']}/{summary['markets_checked']}")
            logger.info(f"  Trades resolved: {summary['total_trades_resolved']}")
            logger.info(f"  Record: {summary['total_wins']}W - {summary['total_losses']}L")
            logger.info(f"  Total P&L: ${summary['total_pnl']:,.2f}")
        
        return summary
    
    def get_resolution_stats(self) -> Dict:
        """Get current resolution statistics from database."""
        conn = self._get_db_connection()
        c = conn.cursor()
        
        # Overall stats
        c.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved_trades,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN resolved = 1 THEN pnl ELSE 0 END) as total_pnl
            FROM trades
        """)
        row = c.fetchone()
        
        stats = {
            "total_trades": row['total_trades'],
            "resolved_trades": row['resolved_trades'] or 0,
            "unresolved_trades": row['total_trades'] - (row['resolved_trades'] or 0),
            "wins": row['wins'] or 0,
            "losses": row['losses'] or 0,
            "total_pnl": row['total_pnl'] or 0,
            "win_rate": 0.0
        }
        
        total_resolved = stats['wins'] + stats['losses']
        if total_resolved > 0:
            stats["win_rate"] = (stats['wins'] / total_resolved) * 100
        
        conn.close()
        return stats


async def main():
    """Run resolution checker as standalone script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Check market resolutions")
    parser.add_argument("-d", "--database", default="whales.db", help="Database path")
    parser.add_argument("-s", "--stats", action="store_true", help="Show stats only")
    args = parser.parse_args()
    
    checker = ResolutionChecker(args.database)
    
    try:
        if args.stats:
            stats = checker.get_resolution_stats()
            print("\n=== Resolution Statistics ===")
            print(f"Total trades: {stats['total_trades']}")
            print(f"Resolved: {stats['resolved_trades']}")
            print(f"Pending: {stats['unresolved_trades']}")
            print(f"Record: {stats['wins']}W - {stats['losses']}L ({stats['win_rate']:.1f}% win rate)")
            print(f"Total P&L: ${stats['total_pnl']:,.2f}")
        else:
            await checker.check_all_unresolved(verbose=True)
    finally:
        await checker.close()


if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
