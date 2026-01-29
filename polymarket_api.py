"""Polymarket API wrapper for whale tracking."""

import asyncio
import aiohttp
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# API endpoints - use DATA API (public) instead of CLOB (requires auth)
DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


class PolymarketAPI:
    def __init__(self):
        self.session = None
        self._rate_limit_delay = 0.3  # Base delay between requests
        self._max_retries = 3
        self._backoff_factor = 2

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"Accept": "application/json"}
            )

    async def _request(self, url: str, params: dict = None) -> Optional[dict]:
        """Make an API request with retry logic and rate limiting."""
        await self._ensure_session()

        for attempt in range(self._max_retries):
            try:
                await asyncio.sleep(self._rate_limit_delay)

                async with self.session.get(url, params=params, timeout=30) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:
                        # Rate limited - exponential backoff
                        delay = self._rate_limit_delay * (self._backoff_factor ** attempt)
                        logger.warning(f"Rate limited, waiting {delay}s before retry")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        text = await response.text()
                        logger.error(f"API error {response.status}: {text[:200]}")
                        return None

            except asyncio.TimeoutError:
                logger.error(f"Request timeout for {url}")
            except aiohttp.ClientError as e:
                logger.error(f"Client error: {e}")

            # Wait before retry
            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._rate_limit_delay * (self._backoff_factor ** attempt))

        return None

    async def get_markets(self, limit: int = 100, offset: int = 0, active: bool = True) -> list:
        """
        Fetch markets from Gamma API.
        Returns list of market objects.
        """
        url = f"{GAMMA_API_BASE}/markets"
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": "false" if active else "true"
        }

        result = await self._request(url, params)
        return result if result else []

    async def get_market(self, condition_id: str) -> Optional[dict]:
        """Get a specific market by condition ID."""
        url = f"{GAMMA_API_BASE}/markets"
        params = {"condition_id": condition_id}
        result = await self._request(url, params)
        if result and len(result) > 0:
            return result[0]
        return None

    async def get_recent_trades(self, limit: int = 500) -> list:
        """
        Get recent trades from the Data API (PUBLIC - no auth needed).
        Returns list of trade objects with wallet addresses.
        """
        url = f"{DATA_API_BASE}/trades"
        params = {"limit": limit}
        result = await self._request(url, params)
        return result if result else []

    async def get_user_positions(self, address: str) -> list:
        """
        Get positions for a specific wallet address.
        Uses Data API (PUBLIC - no auth needed).
        """
        url = f"{DATA_API_BASE}/positions"
        params = {"user": address.lower()}
        result = await self._request(url, params)
        return result if result else []

    async def get_user_trades(self, address: str, limit: int = 100) -> list:
        """
        Get trade history for a wallet address.
        Uses Data API (PUBLIC).
        """
        url = f"{DATA_API_BASE}/trades"
        params = {
            "user": address.lower(),
            "limit": limit
        }
        result = await self._request(url, params)
        return result if result else []

    async def discover_whales(self, min_volume: float = 50000, limit: int = 100) -> list:
        """
        Discover whale wallets by analyzing recent trades.
        Returns list of wallet addresses with their total trade volume.
        """
        whales = {}
        
        logger.info("Fetching recent trades to discover whales...")
        
        # Fetch multiple batches of recent trades
        all_trades = []
        for offset in range(0, 2000, 500):
            trades = await self.get_recent_trades(limit=500)
            if not trades:
                break
            all_trades.extend(trades)
            await asyncio.sleep(0.5)  # Rate limiting
        
        logger.info(f"Analyzing {len(all_trades)} trades for whale activity...")

        for trade in all_trades:
            try:
                wallet = trade.get('proxyWallet', '').lower()
                if not wallet:
                    continue
                    
                size = float(trade.get('size', 0))
                price = float(trade.get('price', 0))
                value = size * price

                if wallet and value > 0:
                    if wallet not in whales:
                        whales[wallet] = {
                            'total_volume': 0,
                            'trade_count': 0,
                            'name': trade.get('pseudonym', ''),
                        }
                    whales[wallet]['total_volume'] += value
                    whales[wallet]['trade_count'] += 1

            except (ValueError, TypeError) as e:
                logger.debug(f"Error processing trade: {e}")
                continue

        # Also check for large individual positions
        logger.info("Checking for wallets with large positions...")
        
        # Get some known active wallets and check their positions
        top_by_volume = sorted(whales.items(), key=lambda x: x[1]['total_volume'], reverse=True)[:50]
        
        for wallet, data in top_by_volume:
            try:
                positions = await self.get_user_positions(wallet)
                total_position_value = 0
                
                for pos in positions:
                    try:
                        size = float(pos.get('size', 0))
                        total_position_value += size
                    except:
                        pass
                
                if total_position_value > 0:
                    whales[wallet]['position_value'] = total_position_value
                    # Add position value to total volume for ranking
                    whales[wallet]['total_volume'] += total_position_value
                    
                await asyncio.sleep(0.2)  # Rate limiting
                
            except Exception as e:
                logger.debug(f"Error checking positions for {wallet[:10]}...: {e}")

        # Filter by minimum volume and sort
        whale_list = [
            {
                "address": addr, 
                "total_volume": data['total_volume'],
                "trade_count": data.get('trade_count', 0),
                "name": data.get('name', ''),
                "position_value": data.get('position_value', 0)
            }
            for addr, data in whales.items()
            if data['total_volume'] >= min_volume
        ]
        whale_list.sort(key=lambda x: x['total_volume'], reverse=True)

        logger.info(f"Found {len(whale_list)} whales with >${min_volume:,.0f} volume")
        return whale_list[:limit]

    async def check_market_resolution(self, condition_id: str) -> Optional[dict]:
        """
        Check if a market has resolved.
        Returns dict with 'resolved' bool and 'resolution' (YES/NO) if resolved.
        """
        market = await self.get_market(condition_id)
        if not market:
            return None

        # Check various resolution indicators
        is_resolved = market.get('resolved', False) or market.get('closed', False)

        result = {
            "resolved": is_resolved,
            "resolution": None,
            "question": market.get('question', '')
        }

        if is_resolved:
            # Determine resolution outcome
            outcome = market.get('outcome', market.get('resolution'))
            if outcome:
                result["resolution"] = outcome.upper() if isinstance(outcome, str) else "YES" if outcome else "NO"
            else:
                # Check outcome prices - winner will be 1.0
                outcome_prices = market.get('outcomePrices', market.get('outcome_prices', []))
                if outcome_prices and len(outcome_prices) >= 2:
                    try:
                        if float(outcome_prices[0]) > 0.9:
                            result["resolution"] = "YES"
                        elif float(outcome_prices[1]) > 0.9:
                            result["resolution"] = "NO"
                    except:
                        pass

        return result

    async def get_active_positions_for_wallet(self, address: str, min_size: float = 5000) -> list:
        """
        Get significant active positions for a wallet.
        Returns positions with size >= min_size.
        """
        positions = await self.get_user_positions(address)

        significant = []
        for pos in positions:
            try:
                size = float(pos.get('size', 0))
                current_value = float(pos.get('currentValue', size))
                
                # Use the larger of size or currentValue
                value = max(size, current_value)

                if value >= min_size:
                    significant.append({
                        "market_id": pos.get('conditionId', ''),
                        "market_question": pos.get('title', 'Unknown'),
                        "side": pos.get('outcome', 'YES').upper(),
                        "size": value,
                        "entry_price": float(pos.get('avgPrice', pos.get('price', 0.5))),
                        "current_price": float(pos.get('curPrice', pos.get('currentPrice', 0.5))),
                        "pnl": float(pos.get('pnl', 0)),
                        "token_id": pos.get('asset', '')
                    })
            except (ValueError, TypeError) as e:
                logger.debug(f"Error parsing position: {e}")
                continue

        return significant

    async def get_new_markets(self, limit: int = 100) -> list:
        """
        Fetch recently created/active markets.
        Returns markets sorted by recency.
        """
        url = f"{GAMMA_API_BASE}/markets"
        params = {
            "limit": limit,
            "active": "true",
            "closed": "false"
        }
        result = await self._request(url, params)
        return result if result else []

    async def get_market_prices(self, condition_id: str) -> dict:
        """Get current YES/NO prices for a market."""
        market = await self.get_market(condition_id)
        if not market:
            return {}
        
        try:
            outcome_prices = market.get('outcomePrices', [])
            if outcome_prices and len(outcome_prices) >= 2:
                return {
                    "yes_price": float(outcome_prices[0]),
                    "no_price": float(outcome_prices[1])
                }
        except:
            pass
        
        return {}

    async def close(self):
        """Close the API session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("API session closed")
