#!/usr/bin/env python3
"""
Enhanced Dashboard Generator v2
- Fetches current market prices for slippage calculation
- Categorizes markets (sports, politics, crypto, etc.)
- Calculates whale skill scores
- Detects multi-whale consensus (THE SIGNAL)
- Prepares data for smart money alerts
"""

import json
import sqlite3
import asyncio
import aiohttp
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
from weather_arbitrage import get_weather_arbitrage_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Polymarket API
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"

# Market categories (regex patterns)
CATEGORY_PATTERNS = {
    "sports": [
        r"will .* win on \d{4}-\d{2}-\d{2}", r"vs\.", r"o/u \d+", r"over/under",
        r"nba", r"nfl", r"mlb", r"nhl", r"soccer", r"football", r"basketball",
        r"premier league", r"champions league", r"world cup", r"super bowl",
        r"fc |ac |bc |sc |cf ", r"manchester|liverpool|chelsea|arsenal|bayern|barcelona|real madrid"
    ],
    "politics": [
        r"election", r"president", r"senate", r"congress", r"governor", r"mayor",
        r"democrat|republican", r"trump|biden|harris", r"vote", r"poll",
        r"primary", r"nominee", r"cabinet", r"impeach"
    ],
    "crypto": [
        r"bitcoin|btc", r"ethereum|eth", r"crypto", r"token", r"defi",
        r"solana|sol", r"cardano|ada", r"binance|bnb", r"$\d+k"
    ],
    "finance": [
        r"fed |federal reserve", r"interest rate", r"inflation", r"gdp",
        r"stock|nasdaq|s&p|dow", r"earnings", r"ipo", r"recession",
        r"treasury", r"bond", r"yield"
    ],
    "tech": [
        r"apple|google|microsoft|amazon|meta|nvidia|tesla",
        r"ai |artificial intelligence", r"launch|release|announce",
        r"iphone|android", r"software|hardware"
    ],
    "entertainment": [
        r"oscar|emmy|grammy|golden globe", r"movie|film|box office",
        r"rotten tomatoes", r"netflix|disney|hbo", r"album|song|music",
        r"celebrity|kardashian"
    ],
    "world": [
        r"china|russia|ukraine|israel|gaza|iran|north korea",
        r"war|military|invasion", r"treaty|sanctions", r"un |nato"
    ]
}


def categorize_market(question: str) -> str:
    """Categorize a market question."""
    q_lower = question.lower()
    
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, q_lower):
                return category
    
    return "other"


def calculate_skill_score(win_rate: float, pnl: float, resolved_trades: int, max_pnl: float = 100000) -> float:
    """
    Calculate whale skill score (0-100).
    
    Components:
    - Win rate (40%): Higher is better, but need enough trades
    - P&L (30%): Normalized against max observed
    - Sample size (30%): More trades = more confidence
    """
    if resolved_trades == 0:
        return 0
    
    # Win rate component (0-40)
    # Adjust for sample size: with few trades, regress toward 50%
    confidence = min(resolved_trades / 20, 1.0)  # Full confidence at 20+ trades
    adjusted_win_rate = 50 + (win_rate - 50) * confidence
    win_rate_score = max(0, min(40, adjusted_win_rate * 0.4))
    
    # P&L component (0-30)
    # Normalize: -max_pnl to +max_pnl -> 0 to 30
    normalized_pnl = max(-1, min(1, pnl / max_pnl))
    pnl_score = (normalized_pnl + 1) * 15  # 0 to 30
    
    # Sample size component (0-30)
    # 0 trades = 0, 10+ trades = full score
    sample_score = min(30, resolved_trades * 3)
    
    total = win_rate_score + pnl_score + sample_score
    return round(total, 1)


async def fetch_current_prices(session: aiohttp.ClientSession, market_ids: List[str]) -> Dict[str, dict]:
    """Fetch current prices for multiple markets."""
    prices = {}
    
    for market_id in market_ids:
        if not market_id:
            continue
        try:
            url = f"{GAMMA_API_BASE}/markets"
            params = {"condition_id": market_id}
            
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        market = data[0]
                        outcome_prices = market.get('outcomePrices', [])
                        if outcome_prices and len(outcome_prices) >= 2:
                            prices[market_id] = {
                                "yes_price": float(outcome_prices[0]),
                                "no_price": float(outcome_prices[1]),
                                "question": market.get('question', '')
                            }
            
            await asyncio.sleep(0.2)  # Rate limit
        except Exception as e:
            logger.debug(f"Error fetching price for {market_id}: {e}")
    
    return prices


def detect_consensus(trades: List[dict], whales: Dict[str, dict], min_skill: float = 40) -> List[dict]:
    """
    Detect markets where multiple skilled whales agree.
    Returns list of consensus signals.
    """
    # Group trades by market
    market_positions = {}
    
    for trade in trades:
        market = trade.get('market_question', '')
        if not market:
            continue
            
        whale_addr = trade.get('whale_address', '')
        whale_data = whales.get(whale_addr, {})
        skill_score = whale_data.get('skill_score', 0)
        
        if market not in market_positions:
            market_positions[market] = {
                "yes": [], "no": [],
                "yes_volume": 0, "no_volume": 0,
                "skilled_yes": 0, "skilled_no": 0,
                "market_id": trade.get('market_id', ''),
                "trades": []
            }
        
        side = trade.get('side', '').upper()
        size = trade.get('size', 0)
        
        entry = {
            "whale": whale_addr,
            "skill_score": skill_score,
            "size": size,
            "entry_price": trade.get('entry_price', 0),
            "entry_time": trade.get('entry_time', '')
        }
        
        if side in ['YES', 'OVER']:
            market_positions[market]["yes"].append(entry)
            market_positions[market]["yes_volume"] += size
            if skill_score >= min_skill:
                market_positions[market]["skilled_yes"] += 1
        elif side in ['NO', 'UNDER']:
            market_positions[market]["no"].append(entry)
            market_positions[market]["no_volume"] += size
            if skill_score >= min_skill:
                market_positions[market]["skilled_no"] += 1
        
        market_positions[market]["trades"].append(entry)
    
    # Build consensus signals
    signals = []
    for market, data in market_positions.items():
        total_whales = len(data["yes"]) + len(data["no"])
        skilled_total = data["skilled_yes"] + data["skilled_no"]
        
        if total_whales < 2:
            continue
        
        # Determine consensus direction
        if data["skilled_yes"] >= 2 and data["skilled_yes"] > data["skilled_no"]:
            consensus_side = "YES"
            consensus_strength = data["skilled_yes"]
            against = data["skilled_no"]
        elif data["skilled_no"] >= 2 and data["skilled_no"] > data["skilled_yes"]:
            consensus_side = "NO"
            consensus_strength = data["skilled_no"]
            against = data["skilled_yes"]
        else:
            consensus_side = "MIXED"
            consensus_strength = 0
            against = 0
        
        # Calculate average entry price for consensus side
        consensus_entries = data["yes"] if consensus_side == "YES" else data["no"]
        avg_entry = sum(e["entry_price"] for e in consensus_entries) / len(consensus_entries) if consensus_entries else 0
        
        signals.append({
            "market": market,
            "market_id": data["market_id"],
            "category": categorize_market(market),
            "consensus_side": consensus_side,
            "consensus_count": consensus_strength,
            "against_count": against,
            "total_whales": total_whales,
            "skilled_whales": skilled_total,
            "yes_count": len(data["yes"]),
            "no_count": len(data["no"]),
            "yes_volume": data["yes_volume"],
            "no_volume": data["no_volume"],
            "avg_entry_price": round(avg_entry, 4),
            "whales_yes": [e["whale"][:10] + "..." for e in data["yes"]],
            "whales_no": [e["whale"][:10] + "..." for e in data["no"]],
            "signal_strength": "🔥 STRONG" if consensus_strength >= 3 else "📊 MODERATE" if consensus_strength >= 2 else "👀 WEAK"
        })
    
    # Sort by signal strength (skilled consensus count)
    signals.sort(key=lambda x: (x["consensus_count"], x["total_whales"]), reverse=True)
    
    return signals


async def generate_enhanced_dashboard(db_path: str = "/app/data/whales.db", output_path: str = "dashboard_data.json"):
    """Generate enhanced dashboard data with skill scores and consensus detection."""
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    logger.info("Generating enhanced dashboard data...")
    
    # === WHALES WITH SKILL SCORES ===
    cursor.execute("""
        SELECT 
            w.address,
            w.total_volume,
            w.win_count,
            w.loss_count,
            COALESCE((SELECT SUM(pnl) FROM trades t WHERE t.whale_address = w.address AND t.resolved = 1), 0) as total_pnl,
            COALESCE((SELECT COUNT(*) FROM trades t WHERE t.whale_address = w.address AND t.resolved = 0), 0) as open_trades
        FROM whales w
        ORDER BY w.total_volume DESC 
        LIMIT 50
    """)
    
    whales = {}
    whale_list = []
    max_pnl = 1  # Will update with actual max
    
    for row in cursor.fetchall():
        resolved = (row['win_count'] or 0) + (row['loss_count'] or 0)
        win_rate = (row['win_count'] * 100.0 / resolved) if resolved > 0 else 0
        pnl = row['total_pnl'] or 0
        max_pnl = max(max_pnl, abs(pnl))
        
        whale_data = {
            "address": row['address'],
            "total_volume": row['total_volume'],
            "win_count": row['win_count'] or 0,
            "loss_count": row['loss_count'] or 0,
            "total_pnl": round(pnl, 2),
            "open_trades": row['open_trades'],
            "win_rate": round(win_rate, 1),
            "resolved_trades": resolved
        }
        whale_list.append(whale_data)
        whales[row['address']] = whale_data
    
    # Calculate skill scores (second pass with actual max_pnl)
    for whale in whale_list:
        whale["skill_score"] = calculate_skill_score(
            whale["win_rate"],
            whale["total_pnl"],
            whale["resolved_trades"],
            max_pnl
        )
        whales[whale["address"]]["skill_score"] = whale["skill_score"]
    
    # Sort by skill score
    whale_list.sort(key=lambda x: x["skill_score"], reverse=True)
    
    # === OPEN TRADES WITH CATEGORIES ===
    cursor.execute("""
        SELECT whale_address, market_question, side, size, entry_price, entry_time, market_id
        FROM trades 
        WHERE resolved = 0 OR resolved IS NULL
        ORDER BY entry_time DESC 
        LIMIT 100
    """)
    
    trades = []
    market_ids = set()
    
    for row in cursor.fetchall():
        trade = dict(row)
        trade["category"] = categorize_market(trade.get("market_question", ""))
        trade["market_id"] = trade.get("market_id", "")
        
        # Add whale skill info
        whale_data = whales.get(trade["whale_address"], {})
        trade["whale_skill"] = whale_data.get("skill_score", 0)
        trade["whale_win_rate"] = whale_data.get("win_rate", 0)
        
        trades.append(trade)
        if trade["market_id"]:
            market_ids.add(trade["market_id"])
    
    # === FETCH CURRENT PRICES ===
    current_prices = {}
    if market_ids:
        logger.info(f"Fetching current prices for {len(market_ids)} markets...")
        async with aiohttp.ClientSession() as session:
            current_prices = await fetch_current_prices(session, list(market_ids))
    
    # Add current prices and slippage to trades
    for trade in trades:
        market_id = trade.get("market_id", "")
        if market_id in current_prices:
            price_data = current_prices[market_id]
            side = trade.get("side", "").upper()
            
            if side in ["YES", "OVER"]:
                current = price_data.get("yes_price", 0)
            else:
                current = price_data.get("no_price", 0)
            
            trade["current_price"] = round(current, 4)
            entry = trade.get("entry_price", 0)
            
            if entry > 0 and current > 0:
                # Slippage = how much worse current price is vs entry
                # Positive = price moved against you (bad)
                slippage = ((current - entry) / entry) * 100
                trade["slippage_pct"] = round(slippage, 1)
            else:
                trade["slippage_pct"] = 0
        else:
            trade["current_price"] = None
            trade["slippage_pct"] = None
    
    # === DETECT CONSENSUS ===
    logger.info("Detecting multi-whale consensus...")
    consensus_signals = detect_consensus(trades, whales, min_skill=40)
    
    # Add current prices to consensus signals
    for signal in consensus_signals:
        market_id = signal.get("market_id", "")
        if market_id in current_prices:
            price_data = current_prices[market_id]
            signal["current_yes_price"] = price_data.get("yes_price", 0)
            signal["current_no_price"] = price_data.get("no_price", 0)
            
            # Calculate slippage for consensus side
            entry = signal.get("avg_entry_price", 0)
            if signal["consensus_side"] == "YES":
                current = signal["current_yes_price"]
            elif signal["consensus_side"] == "NO":
                current = signal["current_no_price"]
            else:
                current = 0
            
            if entry > 0 and current > 0:
                signal["slippage_pct"] = round(((current - entry) / entry) * 100, 1)
            else:
                signal["slippage_pct"] = 0
    
    # === RESOLVED TRADES ===
    cursor.execute("""
        SELECT id, whale_address, market_question, side, size, entry_price, entry_time, outcome, pnl
        FROM trades WHERE resolved = 1
        ORDER BY entry_time DESC LIMIT 50
    """)
    resolved_trades = []
    for row in cursor.fetchall():
        trade = dict(row)
        trade["category"] = categorize_market(trade.get("market_question", ""))
        resolved_trades.append(trade)
    
    # === FADE THE LOSERS ===
    losers = [w for w in whale_list if w["skill_score"] < 40 and w["resolved_trades"] >= 3 and w["total_pnl"] < 0]
    losers.sort(key=lambda x: x["total_pnl"])  # Worst P&L first
    
    # Get loser positions for fading
    loser_addresses = [l["address"] for l in losers[:10]]
    loser_trades = [t for t in trades if t["whale_address"] in loser_addresses]
    
    # === WEATHER ARBITRAGE DATA ===
    logger.info("Generating weather arbitrage data...")
    weather_arbitrage = get_weather_arbitrage_data()
    
    # === STATS ===
    cursor.execute("SELECT COUNT(*) FROM whales")
    whale_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE resolved = 0 OR resolved IS NULL")
    open_trade_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE resolved = 1")
    resolved_trade_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
               SUM(pnl) as total_pnl
        FROM trades WHERE resolved = 1
    """)
    stats_row = cursor.fetchone()
    
    conn.close()
    
    # === BUILD OUTPUT ===
    data = {
        "generated_at": datetime.utcnow().isoformat(),
        "version": "2.0",
        "stats": {
            "whale_count": whale_count,
            "open_trade_count": open_trade_count,
            "resolved_trade_count": resolved_trade_count,
            "total_wins": stats_row['wins'] or 0,
            "total_losses": stats_row['losses'] or 0,
            "total_pnl": round(stats_row['total_pnl'] or 0, 2),
            "consensus_signals": len([s for s in consensus_signals if s["consensus_count"] >= 2]),
            "strong_signals": len([s for s in consensus_signals if s["consensus_count"] >= 3]),
            "weather_opportunities": weather_arbitrage['summary']['total_opportunities'],
            "weather_strong_signals": weather_arbitrage['summary']['strong_signals']
        },
        "whales": whale_list,
        "trades": trades,
        "consensus": consensus_signals,
        "resolved_trades": resolved_trades,
        "fade_candidates": {
            "losers": losers[:10],
            "loser_trades": loser_trades
        },
        "weather_arbitrage": weather_arbitrage
    }
    
    # Write output
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    # Write weather_data.json for the Weather tab
    output_dir = Path(output_path).parent
    weather_data_path = output_dir / "weather_data.json"
    with open(weather_data_path, 'w') as f:
        json.dump(weather_arbitrage, f, indent=2, default=str)
    logger.info(f"Weather data written to {weather_data_path}")

    # Write performance.json for Performance and Paper Trading tabs
    performance_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "whale_tracking": {
            "qualified_whales": len([w for w in whale_list if w["skill_score"] >= 40 and w["resolved_trades"] >= 10]),
            "whale_signal_accuracy": sum(w["win_rate"] for w in whale_list[:10]) / 1000 if whale_list else 0,
            "total_whale_signals": len(consensus_signals),
            "top_whales": [
                {
                    "id": w["address"][:10] + "...",
                    "win_rate": w["win_rate"] / 100,
                    "total_trades": w["resolved_trades"],
                    "avg_edge": 0.15 if w["win_rate"] > 60 else 0.08,
                    "last_signal": datetime.utcnow().isoformat()
                }
                for w in whale_list[:5] if w["resolved_trades"] >= 5
            ]
        },
        "signals": {
            "total_generated": len(consensus_signals),
            "last_24h": [
                {
                    "market": s["market"][:50] + "..." if len(s["market"]) > 50 else s["market"],
                    "signal": "strong_buy" if s["consensus_count"] >= 3 else "buy",
                    "confidence": 0.8 if s["consensus_count"] >= 3 else 0.6,
                    "edge": 0.15 if s["consensus_count"] >= 3 else 0.10,
                    "source": "whale_consensus",
                    "timestamp": datetime.utcnow().isoformat()
                }
                for s in consensus_signals[:10]
            ]
        },
        "paper_trading": {
            "total_trades": resolved_trade_count,
            "win_rate": (stats_row['wins'] / resolved_trade_count) if resolved_trade_count > 0 else 0,
            "total_pnl": round(stats_row['total_pnl'] or 0, 2),
            "average_trade": round((stats_row['total_pnl'] or 0) / resolved_trade_count, 2) if resolved_trade_count > 0 else 0,
            "best_trade": max([t.get("pnl", 0) for t in resolved_trades] or [0]),
            "worst_trade": min([t.get("pnl", 0) for t in resolved_trades] or [0]),
            "trades": [
                {
                    "market": t["market_question"][:40] + "..." if len(t.get("market_question", "")) > 40 else t.get("market_question", "Unknown"),
                    "position": t.get("side", "YES"),
                    "entry_price": t.get("entry_price", 0.5),
                    "exit_price": t.get("entry_price", 0.5) + (0.1 if t.get("outcome") == "WIN" else -0.1),
                    "pnl": t.get("pnl", 0),
                    "status": t.get("outcome", "PENDING"),
                    "date": t.get("entry_time", datetime.utcnow().isoformat()),
                    "signal_source": "whale_consensus"
                }
                for t in resolved_trades[:10]
            ],
            "daily_pnl": {}
        }
    }
    performance_path = output_dir / "performance.json"
    with open(performance_path, 'w') as f:
        json.dump(performance_data, f, indent=2, default=str)
    logger.info(f"Performance data written to {performance_path}")

    logger.info(f"Enhanced dashboard data written to {output_path}")
    logger.info(f"  Whales: {whale_count} (top {len(whale_list)} with scores)")
    logger.info(f"  Open trades: {open_trade_count}")
    logger.info(f"  Consensus signals: {data['stats']['consensus_signals']} ({data['stats']['strong_signals']} strong)")
    logger.info(f"  Fade candidates: {len(losers)}")
    
    return data


def generate_alert_messages(data: dict) -> List[str]:
    """Generate Telegram alert messages for strong signals."""
    alerts = []
    
    strong_signals = [s for s in data.get("consensus", []) if s.get("consensus_count", 0) >= 3]
    
    for signal in strong_signals[:5]:  # Max 5 alerts
        market = signal.get("market", "")[:80]
        side = signal.get("consensus_side", "")
        count = signal.get("consensus_count", 0)
        entry = signal.get("avg_entry_price", 0)
        current = signal.get(f"current_{side.lower()}_price", entry)
        slippage = signal.get("slippage_pct", 0)
        category = signal.get("category", "other").upper()
        
        slippage_emoji = "✅" if abs(slippage) < 5 else "⚠️" if abs(slippage) < 10 else "❌"
        
        msg = f"""🔥 MULTI-WHALE SIGNAL

📊 {market}

Direction: {side}
Skilled Whales: {count} agree
Entry: ${entry:.2f} → Now: ${current:.2f}
Slippage: {slippage:+.1f}% {slippage_emoji}
Category: {category}

{"⚡ Good entry available!" if abs(slippage) < 10 else "⏳ Price moved significantly"}"""
        
        alerts.append(msg)
    
    return alerts


if __name__ == "__main__":
    import sys
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/whales.db"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "dashboard_data.json"
    
    data = asyncio.run(generate_enhanced_dashboard(db_path, output_path))
    
    # Print any strong signals
    alerts = generate_alert_messages(data)
    if alerts:
        print("\n" + "="*50)
        print("ALERT MESSAGES TO SEND:")
        print("="*50)
        for alert in alerts:
            print(alert)
            print("-"*50)
