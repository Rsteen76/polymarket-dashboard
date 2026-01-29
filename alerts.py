"""Telegram alert functions for whale notifications."""

import asyncio
import aiohttp
import ssl
import logging
from typing import Optional

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


class TelegramAlerts:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.session = None
        self._enabled = bool(bot_token and chat_id)
        
        # Create SSL context that doesn't verify (for corporate proxies etc)
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

        if not self._enabled:
            logger.warning("Telegram alerts disabled - missing bot_token or chat_id")

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to the configured Telegram chat.
        Returns True if successful.
        """
        if not self._enabled:
            logger.info(f"[ALERT - Not sent] {text}")
            return False

        await self._ensure_session()

        url = f"{TELEGRAM_API_BASE}{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }

        try:
            async with self.session.post(url, json=payload, timeout=10) as response:
                if response.status == 200:
                    logger.info("Telegram alert sent successfully")
                    return True
                else:
                    error = await response.text()
                    logger.error(f"Telegram error {response.status}: {error}")
                    return False
        except asyncio.TimeoutError:
            logger.error("Telegram request timed out")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"Telegram client error: {e}")
            return False

    def format_address(self, address: str) -> str:
        """Format wallet address for display (truncated)."""
        if len(address) > 12:
            return f"{address[:6]}...{address[-4:]}"
        return address

    def format_money(self, amount: float) -> str:
        """Format dollar amount."""
        return f"${amount:,.0f}"

    async def send_whale_alert(self, wallet: str, market_question: str, side: str,
                                size: float, win_count: int, loss_count: int) -> bool:
        """
        Send a whale trade alert.
        """
        total_trades = win_count + loss_count
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        win_rate_str = f"{win_rate:.0f}% ({win_count}W-{loss_count}L)" if total_trades > 0 else "No history"

        # Truncate market question if too long
        if len(market_question) > 100:
            market_question = market_question[:97] + "..."

        message = f"""🐋 <b>WHALE ALERT</b>

<b>Wallet:</b> <code>{self.format_address(wallet)}</code>
<b>Market:</b> {market_question}
<b>Side:</b> {side}
<b>Size:</b> {self.format_money(size)}
<b>Win rate:</b> {win_rate_str}"""

        return await self.send_message(message)

    async def send_resolution_alert(self, market_question: str, resolution: str,
                                     winning_whales: list, losing_whales: list) -> bool:
        """
        Send alert when a market resolves.
        """
        if len(market_question) > 80:
            market_question = market_question[:77] + "..."

        winners_str = ", ".join([self.format_address(w) for w in winning_whales[:5]]) if winning_whales else "None tracked"
        losers_str = ", ".join([self.format_address(w) for w in losing_whales[:5]]) if losing_whales else "None tracked"

        message = f"""📊 <b>MARKET RESOLVED</b>

<b>Market:</b> {market_question}
<b>Outcome:</b> {resolution}

<b>Winners:</b> {winners_str}
<b>Losers:</b> {losers_str}"""

        return await self.send_message(message)

    async def send_whale_discovery_alert(self, address: str, total_volume: float) -> bool:
        """
        Send alert when a new whale is discovered.
        """
        message = f"""🔍 <b>NEW WHALE DISCOVERED</b>

<b>Wallet:</b> <code>{self.format_address(address)}</code>
<b>Total Volume:</b> {self.format_money(total_volume)}

Now tracking this wallet for future trades."""

        return await self.send_message(message)

    async def send_startup_alert(self, whale_count: int, trade_count: int) -> bool:
        """
        Send alert when tracker starts.
        """
        message = f"""🚀 <b>WHALE TRACKER STARTED</b>

<b>Tracking:</b> {whale_count} whales
<b>Open positions:</b> {trade_count} trades

Monitoring for new positions..."""

        return await self.send_message(message)

    async def send_error_alert(self, error_message: str) -> bool:
        """
        Send alert for critical errors.
        """
        message = f"""⚠️ <b>TRACKER ERROR</b>

{error_message}

Please check the logs."""

        return await self.send_message(message)

    async def send_new_market_alert(self, question: str, slug: str, 
                                      volume: float = 0, liquidity: float = 0,
                                      yes_price: float = None) -> bool:
        """
        Send alert for new market discovery - SNIPE OPPORTUNITY.
        """
        # Truncate question if too long
        if len(question) > 150:
            question = question[:147] + "..."
        
        poly_url = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
        
        price_str = f"\n<b>YES Price:</b> ${yes_price:.2f}" if yes_price else ""
        
        message = f"""🚨 <b>NEW MARKET ALERT</b> 🚨

<b>Market:</b> {question}
{price_str}
<b>Volume:</b> {self.format_money(volume)}
<b>Liquidity:</b> {self.format_money(liquidity)}

<b>Link:</b> {poly_url}

⚡ Early entry opportunity - low liquidity = better prices!"""

        return await self.send_message(message)

    async def send_price_update_alert(self, question: str, timeframe: str,
                                       initial_price: float, current_price: float, 
                                       gain_pct: float) -> bool:
        """
        Send alert when tracked market has significant price movement.
        """
        if len(question) > 100:
            question = question[:97] + "..."
        
        direction = "📈" if gain_pct > 0 else "📉"
        
        message = f"""{direction} <b>PRICE UPDATE ({timeframe})</b>

<b>Market:</b> {question}

<b>Entry price:</b> ${initial_price:.2f}
<b>Current price:</b> ${current_price:.2f}
<b>Change:</b> {gain_pct:+.1f}%

{"✅ Early entry would be profitable!" if gain_pct > 0 else "❌ Price dropped from entry"}"""

        return await self.send_message(message)

    async def send_daily_summary(self, stats: dict) -> bool:
        """
        Send daily summary of whale activity.
        """
        message = f"""📈 <b>DAILY WHALE SUMMARY</b>

<b>New trades:</b> {stats.get('new_trades', 0)}
<b>Resolved trades:</b> {stats.get('resolved_trades', 0)}
<b>Total wins:</b> {stats.get('wins', 0)}
<b>Total losses:</b> {stats.get('losses', 0)}
<b>Net PnL:</b> {self.format_money(stats.get('net_pnl', 0))}

<b>Top performer:</b> {stats.get('top_whale', 'N/A')}"""

        return await self.send_message(message)

    async def close(self):
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Telegram session closed")
