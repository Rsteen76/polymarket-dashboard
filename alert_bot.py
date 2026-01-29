#!/usr/bin/env python3
"""
Telegram Alert Bot for Polymarket Smart Money Signals

Sends alerts when:
1. 3+ skilled whales agree on a market (STRONG SIGNAL)
2. New position from a top-performing whale
3. Whale exits a position (for exit signals)
"""

import json
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Alert state file to track what we've already alerted
STATE_FILE = "/app/data/alert_state.json"


def load_alert_state() -> dict:
    """Load previously sent alerts to avoid duplicates."""
    try:
        if Path(STATE_FILE).exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {"sent_signals": [], "last_check": None}


def save_alert_state(state: dict):
    """Save alert state."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save alert state: {e}")


async def send_telegram_message(bot_token: str, chat_id: str, message: str) -> bool:
    """Send a Telegram message."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Alert sent to {chat_id}")
                    return True
                else:
                    text = await response.text()
                    logger.error(f"Telegram error {response.status}: {text}")
                    return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def format_signal_alert(signal: dict) -> str:
    """Format a consensus signal as a Telegram message."""
    market = signal.get("market", "")[:100]
    side = signal.get("consensus_side", "UNKNOWN")
    count = signal.get("consensus_count", 0)
    against = signal.get("against_count", 0)
    entry = signal.get("avg_entry_price", 0)
    slippage = signal.get("slippage_pct", 0)
    category = signal.get("category", "other").upper()
    
    # Slippage indicator
    if abs(slippage) < 5:
        slippage_status = "✅ Great entry"
    elif abs(slippage) < 10:
        slippage_status = "⚠️ Acceptable"
    else:
        slippage_status = "❌ Price moved"
    
    # Get current price for the side
    if side == "YES":
        current = signal.get("current_yes_price", entry)
    elif side == "NO":
        current = signal.get("current_no_price", entry)
    else:
        current = entry
    
    # Build whale list
    yes_whales = signal.get("whales_yes", [])
    no_whales = signal.get("whales_no", [])
    
    msg = f"""🐋 <b>SMART MONEY SIGNAL</b>

<b>{market}</b>

📊 <b>Direction:</b> {side}
👥 <b>Whales:</b> {count} agree{f' vs {against} against' if against > 0 else ''}
💰 <b>Entry:</b> ${entry:.3f} → <b>Now:</b> ${current:.3f}
📈 <b>Slippage:</b> {slippage:+.1f}% {slippage_status}
🏷️ <b>Category:</b> {category}

<b>YES side:</b> {', '.join(yes_whales[:3]) if yes_whales else 'None'}
<b>NO side:</b> {', '.join(no_whales[:3]) if no_whales else 'None'}

⚡ <i>Multi-whale consensus = higher confidence</i>"""
    
    return msg


def format_new_position_alert(trade: dict, whale: dict) -> str:
    """Format a new whale position alert."""
    market = trade.get("market_question", "")[:100]
    side = trade.get("side", "").upper()
    size = trade.get("size", 0)
    entry = trade.get("entry_price", 0)
    skill = whale.get("skill_score", 0)
    win_rate = whale.get("win_rate", 0)
    pnl = whale.get("total_pnl", 0)
    address = whale.get("address", "")[:10]
    category = trade.get("category", "other").upper()
    
    pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
    
    msg = f"""🐋 <b>NEW WHALE POSITION</b>

<b>{market}</b>

📊 <b>Direction:</b> {side}
💵 <b>Size:</b> ${size:,.0f}
💰 <b>Entry:</b> ${entry:.3f}
🏷️ <b>Category:</b> {category}

<b>Whale Stats:</b>
• Address: {address}...
• Skill Score: {skill:.0f}/100
• Win Rate: {win_rate:.1f}%
• P&L: {pnl_str}

⚡ <i>High-skill whale = better signal</i>"""
    
    return msg


async def check_and_send_alerts(
    data_path: str,
    bot_token: str,
    chat_id: str,
    min_consensus: int = 3,
    min_skill_for_individual: float = 70
):
    """
    Check dashboard data and send alerts for new signals.
    
    Args:
        data_path: Path to dashboard_data.json
        bot_token: Telegram bot token
        chat_id: Telegram chat ID to send to
        min_consensus: Minimum whale consensus count for alerts (default 3)
        min_skill_for_individual: Min skill score to alert on individual trades
    """
    
    # Load data
    try:
        with open(data_path) as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load dashboard data: {e}")
        return
    
    # Load alert state
    state = load_alert_state()
    sent_signals = set(state.get("sent_signals", []))
    
    alerts_sent = 0
    new_sent = []
    
    # Check consensus signals
    for signal in data.get("consensus", []):
        if signal.get("consensus_count", 0) < min_consensus:
            continue
        
        # Create unique key for this signal
        signal_key = f"{signal.get('market', '')}_{signal.get('consensus_side', '')}"
        
        if signal_key in sent_signals:
            continue
        
        # Check slippage - skip if too high
        slippage = abs(signal.get("slippage_pct", 100))
        if slippage > 15:
            logger.info(f"Skipping signal (slippage {slippage}%): {signal.get('market', '')[:50]}")
            continue
        
        # Send alert
        message = format_signal_alert(signal)
        if await send_telegram_message(bot_token, chat_id, message):
            new_sent.append(signal_key)
            alerts_sent += 1
            await asyncio.sleep(1)  # Rate limit
    
    # Check for individual high-skill whale trades
    whales_by_addr = {w["address"]: w for w in data.get("whales", [])}
    
    for trade in data.get("trades", [])[:20]:  # Only recent trades
        whale_addr = trade.get("whale_address", "")
        whale = whales_by_addr.get(whale_addr, {})
        
        skill = whale.get("skill_score", 0)
        if skill < min_skill_for_individual:
            continue
        
        # Create unique key
        trade_key = f"{whale_addr}_{trade.get('market_question', '')}_{trade.get('entry_time', '')}"
        
        if trade_key in sent_signals:
            continue
        
        # Send alert
        message = format_new_position_alert(trade, whale)
        if await send_telegram_message(bot_token, chat_id, message):
            new_sent.append(trade_key)
            alerts_sent += 1
            await asyncio.sleep(1)
    
    # Update state
    if new_sent:
        # Keep last 1000 sent signals
        all_sent = list(sent_signals) + new_sent
        state["sent_signals"] = all_sent[-1000:]
        state["last_check"] = datetime.utcnow().isoformat()
        save_alert_state(state)
    
    logger.info(f"Alert check complete. Sent {alerts_sent} new alerts.")
    return alerts_sent


async def main():
    """Main entry point."""
    import sys
    import os
    
    # Load config
    config_path = "/app/config.json"
    try:
        with open(config_path) as f:
            config = json.load(f)
    except:
        config = {}
    
    bot_token = config.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = config.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        logger.error("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        sys.exit(1)
    
    data_path = sys.argv[1] if len(sys.argv) > 1 else "/app/public/dashboard_data.json"
    
    await check_and_send_alerts(
        data_path=data_path,
        bot_token=bot_token,
        chat_id=chat_id,
        min_consensus=3,
        min_skill_for_individual=70
    )


if __name__ == "__main__":
    asyncio.run(main())
