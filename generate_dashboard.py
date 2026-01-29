#!/usr/bin/env python3
"""
Generate dashboard data JSON from SQLite database.
Run this periodically to update the web dashboard.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def generate_dashboard_data(db_path: str = "/app/data/whales.db", output_path: str = "dashboard_data.json"):
    """Generate JSON data for the web dashboard."""
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    data = {
        "generated_at": datetime.utcnow().isoformat(),
        "stats": {},
        "whales": [],
        "trades": [],
        "resolved_trades": [],
        "new_markets": []
    }
    
    # === STATS ===
    cursor.execute("SELECT COUNT(*) FROM whales")
    data["stats"]["whale_count"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE resolved = 0 OR resolved IS NULL")
    data["stats"]["open_trade_count"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE resolved = 1")
    data["stats"]["resolved_trade_count"] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM seen_markets")
    data["stats"]["market_count"] = cursor.fetchone()[0]
    
    # Overall win/loss stats
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as total_wins,
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as total_losses,
            SUM(CASE WHEN resolved = 1 THEN pnl ELSE 0 END) as total_pnl
        FROM trades
    """)
    row = cursor.fetchone()
    total_wins = row['total_wins'] or 0
    total_losses = row['total_losses'] or 0
    total_pnl = row['total_pnl'] or 0
    
    data["stats"]["total_wins"] = total_wins
    data["stats"]["total_losses"] = total_losses
    data["stats"]["total_pnl"] = round(total_pnl, 2)
    
    total_resolved = total_wins + total_losses
    data["stats"]["avg_win_rate"] = round((total_wins / total_resolved * 100) if total_resolved > 0 else 0, 1)
    
    # === WHALES (with proper stats) ===
    cursor.execute("""
        SELECT 
            w.address,
            w.total_volume,
            w.win_count,
            w.loss_count,
            COALESCE(
                (SELECT SUM(pnl) FROM trades t WHERE t.whale_address = w.address AND t.resolved = 1),
                0
            ) as total_pnl,
            COALESCE(
                (SELECT COUNT(*) FROM trades t WHERE t.whale_address = w.address AND t.resolved = 0),
                0
            ) as open_trades,
            CASE 
                WHEN w.win_count + w.loss_count > 0 
                THEN ROUND(w.win_count * 100.0 / (w.win_count + w.loss_count), 1)
                ELSE 0 
            END as win_rate
        FROM whales w
        ORDER BY w.total_volume DESC 
        LIMIT 20
    """)
    
    for row in cursor.fetchall():
        whale_data = dict(row)
        whale_data['total_pnl'] = round(whale_data['total_pnl'] or 0, 2)
        data["whales"].append(whale_data)
    
    # === OPEN TRADES (recent) ===
    cursor.execute("""
        SELECT whale_address, market_question, side, size, entry_price, entry_time
        FROM trades 
        WHERE resolved = 0 OR resolved IS NULL
        ORDER BY entry_time DESC 
        LIMIT 20
    """)
    data["trades"] = [dict(row) for row in cursor.fetchall()]
    
    # === RESOLVED TRADES (historical) ===
    cursor.execute("""
        SELECT 
            t.id,
            t.whale_address,
            t.market_question,
            t.side,
            t.size,
            t.entry_price,
            t.entry_time,
            t.outcome,
            t.pnl
        FROM trades t
        WHERE t.resolved = 1
        ORDER BY t.entry_time DESC
        LIMIT 50
    """)
    data["resolved_trades"] = [dict(row) for row in cursor.fetchall()]
    
    # === PER-WHALE RESOLVED TRADES (for detailed view) ===
    whale_history = {}
    cursor.execute("""
        SELECT 
            whale_address,
            market_question,
            side,
            size,
            entry_price,
            entry_time,
            outcome,
            pnl
        FROM trades
        WHERE resolved = 1
        ORDER BY entry_time DESC
    """)
    for row in cursor.fetchall():
        addr = row['whale_address']
        if addr not in whale_history:
            whale_history[addr] = []
        if len(whale_history[addr]) < 10:  # Keep last 10 per whale
            whale_history[addr].append({
                "question": row['market_question'],
                "side": row['side'],
                "size": row['size'],
                "entry_price": row['entry_price'],
                "outcome": row['outcome'],
                "pnl": round(row['pnl'] or 0, 2)
            })
    data["whale_history"] = whale_history
    
    # === NEW MARKETS (last 24h) ===
    yesterday = datetime.utcnow() - timedelta(hours=24)
    cursor.execute("""
        SELECT condition_id, slug, question, first_seen, volume, liquidity,
            initial_yes_price, initial_no_price, price_1hr_yes, price_24hr_yes
        FROM seen_markets 
        WHERE first_seen > ? AND initial_yes_price IS NOT NULL
        ORDER BY first_seen DESC 
        LIMIT 20
    """, (yesterday,))
    data["new_markets"] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    # Write JSON
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    
    print(f"Dashboard data written to {output_path}")
    print(f"  Whales: {data['stats']['whale_count']}")
    print(f"  Open trades: {data['stats']['open_trade_count']}")
    print(f"  Resolved trades: {data['stats']['resolved_trade_count']}")
    print(f"  Win rate: {data['stats']['avg_win_rate']}% ({total_wins}W-{total_losses}L)")
    print(f"  Total P&L: ${data['stats']['total_pnl']:,.2f}")
    
    return data


def generate_daily_summary(db_path: str = "whales.db") -> str:
    """Generate a daily summary text for Telegram."""
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get stats
    cursor.execute("SELECT COUNT(*) FROM whales")
    whale_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE resolved = 0 OR resolved IS NULL")
    open_trades = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trades WHERE resolved = 1")
    resolved_trades = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins, 
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
            SUM(pnl) as total_pnl
        FROM trades WHERE resolved = 1
    """)
    row = cursor.fetchone()
    total_wins = row['wins'] or 0
    total_losses = row['losses'] or 0
    total_pnl = row['total_pnl'] or 0
    
    # New markets in last 24h
    yesterday = datetime.utcnow() - timedelta(hours=24)
    cursor.execute("SELECT COUNT(*) FROM seen_markets WHERE first_seen > ?", (yesterday,))
    new_markets_24h = cursor.fetchone()[0]
    
    # Profitable new markets (price went up)
    cursor.execute("""
        SELECT COUNT(*) FROM seen_markets 
        WHERE first_seen > ? 
        AND price_24hr_yes IS NOT NULL 
        AND price_24hr_yes > initial_yes_price
    """, (yesterday,))
    profitable_markets = cursor.fetchone()[0]
    
    # Top whale by volume
    cursor.execute("""
        SELECT address, total_volume, win_count, loss_count 
        FROM whales ORDER BY total_volume DESC LIMIT 1
    """)
    top_whale = cursor.fetchone()
    
    # Top performer by P&L
    cursor.execute("""
        SELECT 
            whale_address,
            SUM(pnl) as total_pnl,
            SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses
        FROM trades 
        WHERE resolved = 1
        GROUP BY whale_address
        ORDER BY total_pnl DESC
        LIMIT 1
    """)
    top_performer = cursor.fetchone()
    
    conn.close()
    
    # Calculate win rate
    win_rate_str = ""
    if total_wins + total_losses > 0:
        win_rate = round(total_wins * 100 / (total_wins + total_losses), 1)
        win_rate_str = f"\n   Win Rate: {win_rate}%"
    
    # Build summary
    summary = f"""DAILY WHALE TRACKER SUMMARY

Whales Tracked: {whale_count}
Open Trades: {open_trades}
Resolved Trades: {resolved_trades}

Overall Record: {total_wins}W - {total_losses}L{win_rate_str}
Total P&L: ${total_pnl:,.2f}

New Markets (24h): {new_markets_24h}
{"Profitable Entries: " + str(profitable_markets) if new_markets_24h > 0 else ""}

Top Whale: {top_whale['address'][:10]}... (${top_whale['total_volume']:,.0f})
   Record: {top_whale['win_count']}W-{top_whale['loss_count']}L"""

    if top_performer and top_performer['total_pnl']:
        pnl = top_performer['total_pnl']
        pnl_sign = "+" if pnl >= 0 else ""
        summary += f"""

Best Performer: {top_performer['whale_address'][:10]}...
   P&L: {pnl_sign}${pnl:,.2f} ({top_performer['wins']}W-{top_performer['losses']}L)"""

    return summary


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        print(generate_daily_summary())
    else:
        generate_dashboard_data()
