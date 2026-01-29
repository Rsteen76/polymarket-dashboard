#!/usr/bin/env python3
"""
NEW SCORING SYSTEM - Based on ACTUAL Performance Only

This replaces the meaningless "skill score" with real performance metrics
based on RESOLVED trades only.
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import math


class PerformanceAnalyzer:
    """Analyzes whale performance based on resolved trades only."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def get_whale_performance(self, whale_address: str, min_resolved_trades: int = 10) -> Optional[Dict]:
        """
        Get performance metrics for a whale.
        Returns None if insufficient data.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Get all resolved trades for this whale
        c.execute("""
            SELECT outcome, pnl, size, entry_time
            FROM trades 
            WHERE whale_address = ? AND resolved = 1
            ORDER BY entry_time
        """, (whale_address,))
        trades = c.fetchall()
        conn.close()
        
        if len(trades) < min_resolved_trades:
            return None
        
        wins = [t for t in trades if t['outcome'] == 'WIN']
        losses = [t for t in trades if t['outcome'] == 'LOSS']
        
        total_trades = len(trades)
        win_count = len(wins)
        loss_count = len(losses)
        
        # Core metrics
        win_rate = (win_count / total_trades) * 100
        
        total_wagered = sum(abs(t['size']) for t in trades)
        total_pnl = sum(t['pnl'] for t in trades)
        roi = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0
        
        # Calculate consistency (standard deviation of returns)
        returns = [t['pnl'] / abs(t['size']) for t in trades if abs(t['size']) > 0]
        if len(returns) > 1:
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(variance)
            
            # Sharpe-like ratio (return / volatility)
            consistency_score = mean_return / std_dev if std_dev > 0 else 0
        else:
            consistency_score = 0
        
        # Calculate max drawdown
        running_pnl = 0
        peak = 0
        max_drawdown = 0
        
        for trade in trades:
            running_pnl += trade['pnl']
            if running_pnl > peak:
                peak = running_pnl
            drawdown = peak - running_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Profit factor (wins / losses)
        total_wins_amount = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        total_losses_amount = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
        profit_factor = total_wins_amount / total_losses_amount if total_losses_amount > 0 else float('inf')
        
        return {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 1),
            "total_wagered": round(total_wagered, 2),
            "total_pnl": round(total_pnl, 2),
            "roi": round(roi, 1),
            "avg_bet_size": round(total_wagered / total_trades, 2),
            "avg_win": round(total_wins_amount / win_count, 2) if win_count > 0 else 0,
            "avg_loss": round(total_losses_amount / loss_count, 2) if loss_count > 0 else 0,
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_drawdown, 2),
            "consistency_score": round(consistency_score, 3),
            "is_profitable": total_pnl > 0,
            "sample_confidence": min(1.0, total_trades / 50),  # Confidence increases with sample size
            "last_trade": trades[-1]['entry_time'] if trades else None
        }
    
    def get_qualified_whales(self, min_resolved_trades: int = 10) -> List[Dict]:
        """Get all whales that meet the minimum criteria for scoring."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Get whales with enough resolved trades
        c.execute("""
            SELECT whale_address, COUNT(*) as resolved_count
            FROM trades 
            WHERE resolved = 1
            GROUP BY whale_address
            HAVING resolved_count >= ?
            ORDER BY resolved_count DESC
        """, (min_resolved_trades,))
        
        whale_candidates = c.fetchall()
        conn.close()
        
        qualified = []
        for row in whale_candidates:
            whale_addr = row['whale_address']
            performance = self.get_whale_performance(whale_addr, min_resolved_trades)
            if performance:
                performance['address'] = whale_addr
                qualified.append(performance)
        
        return qualified
    
    def rank_whales(self, qualified_whales: List[Dict]) -> List[Dict]:
        """
        Rank whales by actual performance.
        Primary sort: ROI
        Secondary sort: Win rate
        Tertiary sort: Sample size
        """
        
        def ranking_score(whale):
            # Weighted score based on multiple factors
            roi_score = whale['roi'] * whale['sample_confidence']  # Adjust for confidence
            win_rate_bonus = (whale['win_rate'] - 50) * 0.5  # Bonus for >50% win rate
            profit_factor_bonus = min(whale['profit_factor'], 3) * 10  # Cap bonus at 3x
            
            return roi_score + win_rate_bonus + profit_factor_bonus
        
        # Sort by ranking score
        qualified_whales.sort(key=ranking_score, reverse=True)
        
        # Add rank
        for i, whale in enumerate(qualified_whales):
            whale['rank'] = i + 1
            whale['ranking_score'] = round(ranking_score(whale), 2)
        
        return qualified_whales
    
    def get_recent_activity(self, whale_address: str, days: int = 7) -> Dict:
        """Get recent activity for a whale."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)
        
        c.execute("""
            SELECT COUNT(*) as trade_count, SUM(size) as volume
            FROM trades 
            WHERE whale_address = ? 
            AND datetime(entry_time) >= datetime(?)
            AND (resolved = 0 OR resolved IS NULL)
        """, (whale_address, cutoff_date.isoformat()))
        
        result = c.fetchone()
        conn.close()
        
        return {
            "recent_trades": result['trade_count'] or 0,
            "recent_volume": result['volume'] or 0
        }
    
    def generate_performance_report(self) -> Dict:
        """Generate a complete performance report."""
        qualified_whales = self.get_qualified_whales(min_resolved_trades=10)
        ranked_whales = self.rank_whales(qualified_whales)
        
        # Overall system stats
        total_resolved_trades = sum(w['total_trades'] for w in qualified_whales)
        total_pnl = sum(w['total_pnl'] for w in qualified_whales)
        profitable_whales = [w for w in qualified_whales if w['is_profitable']]
        
        # Add recent activity to top performers
        for whale in ranked_whales[:10]:  # Top 10 only
            activity = self.get_recent_activity(whale['address'])
            whale.update(activity)
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "methodology": {
                "min_resolved_trades": 10,
                "ranking_criteria": ["ROI (confidence-adjusted)", "Win Rate", "Sample Size"],
                "data_source": "Resolved trades only - no speculation"
            },
            "summary": {
                "qualified_whales": len(qualified_whales),
                "total_resolved_trades": total_resolved_trades,
                "total_tracked_pnl": round(total_pnl, 2),
                "profitable_whales": len(profitable_whales),
                "profitability_rate": round(len(profitable_whales) / len(qualified_whales) * 100, 1) if qualified_whales else 0
            },
            "top_performers": ranked_whales[:20],
            "all_qualified": ranked_whales
        }
        
        return report


def main():
    analyzer = PerformanceAnalyzer("data/whales.db")
    
    print("=== NEW SCORING SYSTEM - RESOLVED TRADES ONLY ===")
    report = analyzer.generate_performance_report()
    
    print(f"\nQualified whales: {report['summary']['qualified_whales']}")
    print(f"Total resolved trades analyzed: {report['summary']['total_resolved_trades']}")
    print(f"Profitable whales: {report['summary']['profitable_whales']}")
    print(f"Overall system P&L: ${report['summary']['total_tracked_pnl']:,.2f}")
    
    print("\n=== TOP 10 PERFORMERS ===")
    for whale in report['top_performers'][:10]:
        print(f"\n#{whale['rank']} - {whale['address'][:10]}...")
        print(f"  Record: {whale['win_count']}W-{whale['loss_count']}L ({whale['win_rate']}%)")
        print(f"  ROI: {whale['roi']:+.1f}% | P&L: ${whale['total_pnl']:+,.2f}")
        print(f"  Volume: ${whale['total_wagered']:,.0f} | Trades: {whale['total_trades']}")
        if whale.get('recent_trades', 0) > 0:
            print(f"  Recent: {whale['recent_trades']} trades, ${whale['recent_volume']:,.0f} volume")
    
    # Save report
    with open('performance_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n=== Report saved to performance_report.json ===")


if __name__ == "__main__":
    main()