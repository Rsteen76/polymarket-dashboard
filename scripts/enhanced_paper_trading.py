#!/usr/bin/env python3
"""
ENHANCED PAPER TRADING SYSTEM

Auto-executes paper trades based on signals and tracks performance.
This proves the system works before deploying real capital.
"""

import sqlite3
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaperTradingSystem:
    """Enhanced paper trading system that tracks signal performance."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.paper_trade_size = 100  # $100 per paper trade
        self.ensure_tables()
    
    def ensure_tables(self):
        """Ensure paper trading tables exist."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Create paper_trades table
        c.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                market_id TEXT,
                market_question TEXT,
                direction TEXT,
                entry_price REAL,
                size REAL,
                whale_address TEXT,
                whale_win_rate REAL,
                whale_resolved_trades INTEGER,
                edge_estimate REAL,
                confidence TEXT,
                created_at TEXT,
                resolved_at TEXT,
                outcome TEXT,
                exit_price REAL,
                pnl REAL,
                active BOOLEAN DEFAULT TRUE,
                UNIQUE(signal_id)
            )
        """)
        
        # Create paper_trading_performance table
        c.execute("""
            CREATE TABLE IF NOT EXISTS paper_trading_performance (
                date TEXT PRIMARY KEY,
                trades_opened INTEGER DEFAULT 0,
                trades_closed INTEGER DEFAULT 0,
                daily_pnl REAL DEFAULT 0,
                cumulative_pnl REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                active_trades INTEGER DEFAULT 0,
                generated_at TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("Paper trading tables ensured")
    
    def record_signal_as_paper_trade(self, signal: Dict) -> bool:
        """Record a signal as a paper trade."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            c.execute("""
                INSERT OR IGNORE INTO paper_trades (
                    signal_id, market_id, market_question, direction, entry_price,
                    size, whale_address, whale_win_rate, whale_resolved_trades,
                    edge_estimate, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal['signal_id'],
                signal['market_id'],
                signal['market_question'],
                signal['direction'],
                signal['price_data']['recommended_price'],
                self.paper_trade_size,
                signal['whale_address'],
                signal['whale_stats']['win_rate'],
                signal['whale_stats']['resolved_trades'],
                signal['edge_estimate'],
                signal['confidence'],
                datetime.now().isoformat()
            ))
            
            if c.rowcount > 0:
                conn.commit()
                logger.info(f"Paper trade recorded: {signal['market_question'][:40]}... - {signal['direction']}")
                return True
            else:
                logger.debug(f"Paper trade already exists: {signal['signal_id']}")
                return False
                
        except Exception as e:
            logger.error(f"Error recording paper trade: {e}")
            return False
        finally:
            conn.close()
    
    def check_paper_trade_resolutions(self):
        """Check if any paper trades have resolved and update them."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Get active paper trades
        c.execute("""
            SELECT * FROM paper_trades 
            WHERE active = TRUE AND resolved_at IS NULL
        """)
        active_trades = c.fetchall()
        
        resolved_count = 0
        
        for trade in active_trades:
            market_id = trade['market_id']
            
            # Check if this market has resolved in the main trades table
            c.execute("""
                SELECT resolved, outcome, pnl, entry_time 
                FROM trades 
                WHERE market_id = ? AND resolved = 1 
                ORDER BY entry_time DESC LIMIT 1
            """, (market_id,))
            
            resolution = c.fetchone()
            if resolution:
                # Market has resolved
                direction = trade['direction'].upper()
                actual_outcome = resolution['outcome']  # WIN or LOSS from whale's perspective
                
                # For paper trade, we need to determine if OUR direction won
                # This is tricky - we need to know what the actual market outcome was
                # Let's check the markets table for the official resolution
                c.execute("""
                    SELECT resolution FROM markets 
                    WHERE market_id = ?
                """, (market_id,))
                market_resolution = c.fetchone()
                
                if market_resolution and market_resolution['resolution']:
                    market_winner = market_resolution['resolution'].upper()  # YES or NO
                    
                    # Determine if our paper trade won
                    paper_won = (direction == market_winner)
                    paper_outcome = "WIN" if paper_won else "LOSS"
                    
                    # Calculate P&L for paper trade
                    entry_price = trade['entry_price']
                    size = trade['size']
                    
                    if paper_won:
                        # Calculate profit: size * (1 - entry_price) / entry_price
                        shares = size / entry_price
                        pnl = shares - size  # profit
                    else:
                        pnl = -size  # lost the stake
                    
                    # Update paper trade
                    c.execute("""
                        UPDATE paper_trades 
                        SET resolved_at = ?, outcome = ?, exit_price = ?, 
                            pnl = ?, active = FALSE
                        WHERE id = ?
                    """, (
                        datetime.now().isoformat(),
                        paper_outcome,
                        1.0 if paper_won else 0.0,  # Binary outcome prices
                        round(pnl, 2),
                        trade['id']
                    ))
                    
                    resolved_count += 1
                    logger.info(f"Paper trade resolved: {trade['market_question'][:40]}... - {paper_outcome} (${pnl:+.2f})")
        
        if resolved_count > 0:
            conn.commit()
            logger.info(f"Resolved {resolved_count} paper trades")
            self.update_daily_performance()
        
        conn.close()
        return resolved_count
    
    def update_daily_performance(self):
        """Update daily performance statistics."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        today = datetime.now().date().isoformat()
        
        # Count trades opened today
        c.execute("""
            SELECT COUNT(*) as opened
            FROM paper_trades 
            WHERE date(created_at) = date(?)
        """, (today,))
        opened_today = c.fetchone()['opened']
        
        # Count trades closed today
        c.execute("""
            SELECT COUNT(*) as closed, 
                   SUM(pnl) as daily_pnl,
                   SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins
            FROM paper_trades 
            WHERE date(resolved_at) = date(?)
        """, (today,))
        closed_data = c.fetchone()
        
        closed_today = closed_data['closed'] or 0
        daily_pnl = closed_data['daily_pnl'] or 0
        wins_today = closed_data['wins'] or 0
        
        # Calculate win rate for today
        win_rate_today = (wins_today / closed_today * 100) if closed_today > 0 else 0
        
        # Get cumulative P&L
        c.execute("""
            SELECT SUM(pnl) as cumulative_pnl
            FROM paper_trades 
            WHERE resolved_at IS NOT NULL
        """)
        cumulative_pnl = c.fetchone()['cumulative_pnl'] or 0
        
        # Count active trades
        c.execute("""
            SELECT COUNT(*) as active
            FROM paper_trades 
            WHERE active = TRUE
        """)
        active_trades = c.fetchone()['active']
        
        # Insert or update today's performance
        c.execute("""
            INSERT OR REPLACE INTO paper_trading_performance (
                date, trades_opened, trades_closed, daily_pnl, cumulative_pnl,
                win_rate, active_trades, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            today, opened_today, closed_today, round(daily_pnl, 2),
            round(cumulative_pnl, 2), round(win_rate_today, 1),
            active_trades, datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
    
    def get_performance_summary(self, days: int = 30) -> Dict:
        """Get performance summary for the last N days."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        cutoff_date = (datetime.now() - timedelta(days=days)).date().isoformat()
        
        # Overall stats
        c.execute("""
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl,
                COUNT(CASE WHEN active = TRUE THEN 1 END) as active_trades
            FROM paper_trades
            WHERE date(created_at) >= date(?)
        """, (cutoff_date,))
        
        stats = dict(c.fetchone())
        
        # Calculate derived metrics
        total_resolved = (stats['wins'] or 0) + (stats['losses'] or 0)
        stats['win_rate'] = round((stats['wins'] or 0) / total_resolved * 100, 1) if total_resolved > 0 else 0
        stats['total_pnl'] = round(stats['total_pnl'] or 0, 2)
        stats['avg_pnl'] = round(stats['avg_pnl'] or 0, 2)
        
        # Daily performance
        c.execute("""
            SELECT date, trades_closed, daily_pnl, win_rate, cumulative_pnl
            FROM paper_trading_performance
            WHERE date >= date(?)
            ORDER BY date DESC
            LIMIT 10
        """, (cutoff_date,))
        
        daily_performance = [dict(row) for row in c.fetchall()]
        
        # Top performing signals
        c.execute("""
            SELECT whale_address, confidence, edge_estimate, outcome, pnl, market_question
            FROM paper_trades
            WHERE resolved_at IS NOT NULL AND date(created_at) >= date(?)
            ORDER BY pnl DESC
            LIMIT 5
        """, (cutoff_date,))
        
        top_trades = [dict(row) for row in c.fetchall()]
        
        # Confidence level breakdown
        c.execute("""
            SELECT 
                confidence,
                COUNT(*) as count,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl
            FROM paper_trades
            WHERE resolved_at IS NOT NULL AND date(created_at) >= date(?)
            GROUP BY confidence
            ORDER BY avg_pnl DESC
        """, (cutoff_date,))
        
        confidence_breakdown = []
        for row in c.fetchall():
            data = dict(row)
            total = data['count']
            wins = data['wins'] or 0
            data['win_rate'] = round(wins / total * 100, 1) if total > 0 else 0
            data['avg_pnl'] = round(data['avg_pnl'] or 0, 2)
            confidence_breakdown.append(data)
        
        conn.close()
        
        return {
            "period_days": days,
            "summary": stats,
            "daily_performance": daily_performance,
            "top_trades": top_trades,
            "confidence_breakdown": confidence_breakdown,
            "generated_at": datetime.now().isoformat()
        }
    
    def process_new_signals(self, signals_file: str = "trade_signals.json") -> int:
        """Process new signals from signals file and record as paper trades."""
        if not os.path.exists(signals_file):
            logger.warning(f"Signals file {signals_file} not found")
            return 0
        
        with open(signals_file, 'r') as f:
            signals_data = json.load(f)
        
        signals = signals_data.get('signals', [])
        new_trades = 0
        
        for signal in signals:
            if self.record_signal_as_paper_trade(signal):
                new_trades += 1
        
        if new_trades > 0:
            logger.info(f"Recorded {new_trades} new paper trades")
            self.update_daily_performance()
        
        return new_trades
    
    def get_system_proof(self) -> Dict:
        """Get proof that the system works - key metrics for dashboard."""
        performance = self.get_performance_summary(30)
        stats = performance['summary']
        
        return {
            "system_status": "LIVE" if stats['total_trades'] > 10 else "TESTING",
            "total_paper_trades": stats['total_trades'],
            "win_rate": stats['win_rate'],
            "total_pnl": stats['total_pnl'],
            "active_trades": stats['active_trades'],
            "avg_trade_pnl": stats['avg_pnl'],
            "track_record": f"{stats['wins']}W-{stats['losses']}L",
            "generated_at": datetime.now().isoformat()
        }


def main():
    """Run paper trading system update."""
    system = PaperTradingSystem("data/whales.db")
    
    print("=== PAPER TRADING SYSTEM UPDATE ===")
    
    # Process any new signals
    new_trades = system.process_new_signals()
    
    # Check for resolutions
    resolved = system.check_paper_trade_resolutions()
    
    # Get performance
    performance = system.get_performance_summary()
    stats = performance['summary']
    
    print(f"\nNew paper trades: {new_trades}")
    print(f"Resolved trades: {resolved}")
    print(f"Total paper trades: {stats['total_trades']}")
    print(f"Win rate: {stats['win_rate']}%")
    print(f"Total P&L: ${stats['total_pnl']:+.2f}")
    print(f"Active trades: {stats['active_trades']}")
    
    if stats['total_trades'] > 0:
        print("\n=== CONFIDENCE BREAKDOWN ===")
        for conf in performance['confidence_breakdown']:
            print(f"{conf['confidence']}: {conf['count']} trades, {conf['win_rate']}% WR, ${conf['avg_pnl']:+.2f} avg")
    
    # Save performance report
    with open('paper_trading_performance.json', 'w') as f:
        json.dump(performance, f, indent=2)
    
    # Save system proof
    proof = system.get_system_proof()
    with open('system_proof.json', 'w') as f:
        json.dump(proof, f, indent=2)
    
    print(f"\n=== Reports saved to paper_trading_performance.json and system_proof.json ===")


if __name__ == "__main__":
    main()