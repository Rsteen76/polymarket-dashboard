#!/usr/bin/env python3
"""
NEW POLYMARKET DASHBOARD - MONEY MAKER EDITION

This is the rebuilt dashboard focused on making money, not just looking pretty.
Based on ACTUAL performance, not speculation.
"""

import json
import sqlite3
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import logging
import sys
import os

# Add scripts to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from new_scoring_system import PerformanceAnalyzer
from trade_signals import TradeSignalsGenerator
from enhanced_paper_trading import PaperTradingSystem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MoneyMakerDashboard:
    """The rebuilt dashboard focused on actionable intelligence."""
    
    def __init__(self, db_path: str = "data/whales.db"):
        self.db_path = db_path
        self.analyzer = PerformanceAnalyzer(db_path)
        self.signals_generator = TradeSignalsGenerator(db_path)
        self.paper_trading = PaperTradingSystem(db_path)
    
    def get_resolution_stats(self) -> Dict:
        """Get current resolution statistics."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Overall resolution stats
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
            "total_pnl": round(row['total_pnl'] or 0, 2),
            "resolution_rate": round((row['resolved_trades'] or 0) / row['total_trades'] * 100, 1) if row['total_trades'] > 0 else 0
        }
        
        if stats['resolved_trades'] > 0:
            stats["win_rate"] = round(stats['wins'] / stats['resolved_trades'] * 100, 1)
        else:
            stats["win_rate"] = 0
        
        conn.close()
        return stats
    
    def get_whale_count_by_performance(self) -> Dict:
        """Get whale counts segmented by performance level."""
        qualified_whales = self.analyzer.get_qualified_whales(min_resolved_trades=10)
        ranked_whales = self.analyzer.rank_whales(qualified_whales)
        
        profitable = len([w for w in ranked_whales if w['is_profitable']])
        high_performers = len([w for w in ranked_whales if w['win_rate'] >= 60 and w['roi'] >= 10])
        
        return {
            "total_qualified": len(ranked_whales),
            "profitable": profitable,
            "high_performers": high_performers,
            "unqualified": self._count_unqualified_whales() - len(ranked_whales)
        }
    
    def _count_unqualified_whales(self) -> int:
        """Count total whales in system."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM whales")
        total = c.fetchone()[0]
        conn.close()
        return total
    
    async def generate_dashboard_data(self) -> Dict:
        """Generate complete dashboard data."""
        logger.info("Generating new money-maker dashboard...")
        
        # 1. Resolution and data quality stats
        resolution_stats = self.get_resolution_stats()
        
        # 2. Performance analysis (qualified whales only)
        performance_report = self.analyzer.generate_performance_report()
        
        # 3. Trade signals
        try:
            signals = await self.signals_generator.generate_signals()
            consensus_signals = await self.signals_generator.detect_consensus_signals(signals)
        except Exception as e:
            logger.error(f"Error generating signals: {e}")
            signals = []
            consensus_signals = []
        
        # 4. Paper trading performance
        paper_performance = self.paper_trading.get_performance_summary(30)
        system_proof = self.paper_trading.get_system_proof()
        
        # 5. Whale performance tiers
        whale_tiers = self.get_whale_count_by_performance()
        
        # Build complete dashboard data
        dashboard_data = {
            "generated_at": datetime.now().isoformat(),
            "version": "MoneyMaker v1.0",
            "methodology": {
                "data_source": "Resolved trades only - no speculation",
                "minimum_sample_size": 10,
                "signal_criteria": {
                    "min_win_rate": 60,
                    "min_roi": 10,
                    "min_resolved_trades": 20
                }
            },
            "system_health": {
                "resolution_rate": resolution_stats["resolution_rate"],
                "data_quality": "HIGH" if resolution_stats["resolution_rate"] > 50 else "IMPROVING",
                "total_resolved_trades": resolution_stats["resolved_trades"],
                "tracking_since": self._get_earliest_trade_date()
            },
            "paper_trading_proof": system_proof,
            "overview": {
                "resolution_stats": resolution_stats,
                "whale_tiers": whale_tiers,
                "qualified_whales": len(performance_report.get('top_performers', [])),
                "active_signals": len(signals),
                "consensus_signals": len(consensus_signals)
            },
            "performance": {
                "top_whales": performance_report.get('top_performers', [])[:10],
                "performance_summary": performance_report.get('summary', {}),
                "methodology_note": "Based on resolved trades only. Whales need 10+ resolved trades to qualify."
            },
            "signals": {
                "active_count": len(signals),
                "high_confidence": len([s for s in signals if s.get('confidence') == 'HIGH']),
                "top_signals": signals[:5],
                "consensus": consensus_signals[:3],
                "criteria": self.signals_generator.__dict__
            },
            "paper_trading": {
                "system_proof": system_proof,
                "performance": paper_performance['summary'],
                "recent_trades": paper_performance.get('daily_performance', [])[:7],
                "confidence_breakdown": paper_performance.get('confidence_breakdown', [])
            },
            "alerts": self._generate_alerts(resolution_stats, signals, system_proof),
            "next_steps": self._generate_next_steps(resolution_stats, whale_tiers, system_proof)
        }
        
        return dashboard_data
    
    def _get_earliest_trade_date(self) -> str:
        """Get the earliest trade date for context."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT MIN(entry_time) FROM trades")
        result = c.fetchone()[0]
        conn.close()
        return result or "Unknown"
    
    def _generate_alerts(self, resolution_stats: Dict, signals: List, system_proof: Dict) -> List:
        """Generate important alerts for the user."""
        alerts = []
        
        # Data quality alert
        if resolution_stats["resolution_rate"] < 50:
            alerts.append({
                "type": "warning",
                "priority": "high",
                "message": f"Only {resolution_stats['resolution_rate']}% of trades resolved. Running backfill...",
                "action": "Resolution checker is processing historical data"
            })
        
        # High confidence signals
        high_conf_signals = len([s for s in signals if s.get('confidence') == 'HIGH'])
        if high_conf_signals > 0:
            alerts.append({
                "type": "opportunity",
                "priority": "medium",
                "message": f"{high_conf_signals} high-confidence signals available",
                "action": "Review signals tab for trading opportunities"
            })
        
        # Paper trading performance
        if system_proof.get('win_rate', 0) > 60 and system_proof.get('total_paper_trades', 0) > 20:
            alerts.append({
                "type": "success",
                "priority": "low",
                "message": f"System proven: {system_proof['win_rate']}% win rate on {system_proof['total_paper_trades']} paper trades",
                "action": "Consider deploying real capital"
            })
        
        return alerts
    
    def _generate_next_steps(self, resolution_stats: Dict, whale_tiers: Dict, system_proof: Dict) -> List:
        """Generate recommended next steps."""
        steps = []
        
        # Data quality steps
        if resolution_stats["resolution_rate"] < 90:
            steps.append("Wait for resolution backfill to complete for better data quality")
        
        # Whale qualification steps
        if whale_tiers["high_performers"] < 5:
            steps.append("Need more historical data - only few whales meet performance criteria")
        
        # Paper trading steps
        if system_proof.get('total_paper_trades', 0) < 50:
            steps.append("Continue paper trading to build track record before real money")
        elif system_proof.get('win_rate', 0) > 55:
            steps.append("Paper trading shows promise - consider starting with small real trades")
        
        return steps
    
    async def generate_html_dashboard(self, output_path: str = "money_maker_dashboard.html"):
        """Generate the HTML dashboard."""
        dashboard_data = await self.generate_dashboard_data()
        
        # Save JSON data
        with open('money_maker_data.json', 'w') as f:
            json.dump(dashboard_data, f, indent=2)
        
        # Generate HTML (template would be more sophisticated in real implementation)
        html_content = self._generate_html_template(dashboard_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Dashboard generated: {output_path}")
        return dashboard_data
    
    def _generate_html_template(self, data: Dict) -> str:
        """Generate HTML dashboard (simplified version)."""
        system_proof = data['paper_trading_proof']
        overview = data['overview']
        alerts = data['alerts']
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Money Maker - Live Performance Dashboard</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background: #0a0a0a; color: #fff; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .header h1 {{ color: #00ff88; margin: 0; font-size: 2.5rem; }}
        .header p {{ color: #888; margin: 5px 0; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; }}
        .card h3 {{ margin-top: 0; color: #fff; }}
        .metric {{ display: flex; justify-content: space-between; margin: 10px 0; }}
        .metric-value {{ font-weight: bold; }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4444; }}
        .neutral {{ color: #ffaa00; }}
        .alert {{ background: #2a1a1a; border-left: 4px solid #ffaa00; padding: 15px; margin: 10px 0; }}
        .alert.success {{ border-color: #00ff88; }}
        .alert.warning {{ border-color: #ffaa00; }}
        .alert.error {{ border-color: #ff4444; }}
        .signals-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        .signals-table th, .signals-table td {{ padding: 10px; text-align: left; border-bottom: 1px solid #333; }}
        .signals-table th {{ background: #2a2a2a; }}
        .status {{ font-weight: bold; padding: 4px 8px; border-radius: 4px; }}
        .status.live {{ background: #00ff88; color: #000; }}
        .status.testing {{ background: #ffaa00; color: #000; }}
        .tab-container {{ margin-top: 30px; }}
        .tabs {{ display: flex; margin-bottom: 20px; }}
        .tab {{ background: #2a2a2a; border: 1px solid #444; padding: 10px 20px; cursor: pointer; margin-right: 5px; }}
        .tab.active {{ background: #00ff88; color: #000; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        .timestamp {{ color: #666; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💰 Polymarket Money Maker</h1>
            <p>Whale tracker that actually makes money - not just pretty displays</p>
            <p class="timestamp">Generated: {data['generated_at']}</p>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>📊 System Status</h3>
                <div class="metric">
                    <span>Status:</span>
                    <span class="status {system_proof['system_status'].lower()}">{system_proof['system_status']}</span>
                </div>
                <div class="metric">
                    <span>Data Quality:</span>
                    <span class="metric-value">{data['system_health']['data_quality']}</span>
                </div>
                <div class="metric">
                    <span>Resolution Rate:</span>
                    <span class="metric-value">{data['system_health']['resolution_rate']}%</span>
                </div>
                <div class="metric">
                    <span>Qualified Whales:</span>
                    <span class="metric-value">{overview['qualified_whales']}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>📈 Paper Trading Proof</h3>
                <div class="metric">
                    <span>Total Trades:</span>
                    <span class="metric-value">{system_proof['total_paper_trades']}</span>
                </div>
                <div class="metric">
                    <span>Win Rate:</span>
                    <span class="metric-value positive">{system_proof['win_rate']}%</span>
                </div>
                <div class="metric">
                    <span>Total P&L:</span>
                    <span class="metric-value {'positive' if system_proof['total_pnl'] >= 0 else 'negative'}">${system_proof['total_pnl']:+.2f}</span>
                </div>
                <div class="metric">
                    <span>Track Record:</span>
                    <span class="metric-value">{system_proof['track_record']}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>🎯 Active Signals</h3>
                <div class="metric">
                    <span>Total Signals:</span>
                    <span class="metric-value">{data['signals']['active_count']}</span>
                </div>
                <div class="metric">
                    <span>High Confidence:</span>
                    <span class="metric-value positive">{data['signals']['high_confidence']}</span>
                </div>
                <div class="metric">
                    <span>Consensus:</span>
                    <span class="metric-value">{len(data['signals']['consensus'])}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>🐋 Whale Performance</h3>
                <div class="metric">
                    <span>High Performers:</span>
                    <span class="metric-value positive">{overview['whale_tiers']['high_performers']}</span>
                </div>
                <div class="metric">
                    <span>Profitable:</span>
                    <span class="metric-value">{overview['whale_tiers']['profitable']}</span>
                </div>
                <div class="metric">
                    <span>Resolved Trades:</span>
                    <span class="metric-value">{overview['resolution_stats']['resolved_trades']}</span>
                </div>
            </div>
        </div>
        
        <!-- Alerts -->
        {"".join(f'<div class="alert {alert["type"]}"><strong>{alert["message"]}</strong><br><small>{alert["action"]}</small></div>' for alert in alerts)}
        
        <!-- Tabs -->
        <div class="tab-container">
            <div class="tabs">
                <div class="tab active" onclick="showTab('signals')">🎯 Trade Signals</div>
                <div class="tab" onclick="showTab('performance')">📊 Whale Performance</div>
                <div class="tab" onclick="showTab('paper-trading')">📈 Paper Trading</div>
                <div class="tab" onclick="showTab('methodology')">🧠 How It Works</div>
            </div>
            
            <div id="signals" class="tab-content active">
                <div class="card">
                    <h3>🎯 Current Trade Signals</h3>
                    {self._format_signals_table(data['signals']['top_signals'])}
                </div>
            </div>
            
            <div id="performance" class="tab-content">
                <div class="card">
                    <h3>📊 Top Performing Whales</h3>
                    {self._format_whales_table(data['performance']['top_whales'])}
                </div>
            </div>
            
            <div id="paper-trading" class="tab-content">
                <div class="card">
                    <h3>📈 Paper Trading Performance</h3>
                    <p>Theoretical performance based on signal execution:</p>
                    {self._format_paper_trading_stats(data['paper_trading']['performance'])}
                </div>
            </div>
            
            <div id="methodology" class="tab-content">
                <div class="card">
                    <h3>🧠 Why This Works</h3>
                    <p><strong>Data-Driven Approach:</strong> Only uses resolved trades - no speculation or unproven metrics.</p>
                    <p><strong>Proven Performance:</strong> Whales must have 10+ resolved trades and 60%+ win rate to generate signals.</p>
                    <p><strong>Paper Trading Validation:</strong> All signals are paper-traded first to prove the system works.</p>
                    <p><strong>Edge Estimation:</strong> Historical whale performance projects expected edge on new trades.</p>
                    <p><strong>Consensus Detection:</strong> When multiple proven whales agree, confidence increases.</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function showTab(tabId) {{
            // Hide all tab contents
            const contents = document.querySelectorAll('.tab-content');
            contents.forEach(content => content.classList.remove('active'));
            
            // Remove active class from all tabs
            const tabs = document.querySelectorAll('.tab');
            tabs.forEach(tab => tab.classList.remove('active'));
            
            // Show selected tab content
            document.getElementById(tabId).classList.add('active');
            
            // Add active class to clicked tab
            event.target.classList.add('active');
        }}
    </script>
</body>
</html>
"""
        return html
    
    def _format_signals_table(self, signals: List) -> str:
        if not signals:
            return "<p>No active signals. Waiting for qualified whale activity.</p>"
        
        rows = []
        for signal in signals:
            whale_short = signal['whale_address'][:10] + "..."
            market_short = signal['market_question'][:40] + "..." if len(signal['market_question']) > 40 else signal['market_question']
            
            rows.append(f"""
                <tr>
                    <td>{signal['direction']}</td>
                    <td>{market_short}</td>
                    <td>{whale_short}</td>
                    <td>{signal['whale_stats']['win_rate']}%</td>
                    <td>{signal['edge_estimate']:+.1f}%</td>
                    <td><span class="status {'positive' if signal['confidence'] == 'HIGH' else 'neutral'}">{signal['confidence']}</span></td>
                </tr>
            """)
        
        return f"""
            <table class="signals-table">
                <thead>
                    <tr><th>Direction</th><th>Market</th><th>Whale</th><th>Win Rate</th><th>Edge</th><th>Confidence</th></tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        """
    
    def _format_whales_table(self, whales: List) -> str:
        if not whales:
            return "<p>No qualified whales yet. Need 10+ resolved trades per whale.</p>"
        
        rows = []
        for whale in whales:
            whale_short = whale['address'][:10] + "..."
            
            rows.append(f"""
                <tr>
                    <td>#{whale.get('rank', 'N/A')}</td>
                    <td>{whale_short}</td>
                    <td>{whale['win_count']}W-{whale['loss_count']}L</td>
                    <td>{whale['win_rate']}%</td>
                    <td>{whale['roi']:+.1f}%</td>
                    <td>${whale['total_pnl']:+.0f}</td>
                </tr>
            """)
        
        return f"""
            <table class="signals-table">
                <thead>
                    <tr><th>Rank</th><th>Whale</th><th>Record</th><th>Win Rate</th><th>ROI</th><th>P&L</th></tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        """
    
    def _format_paper_trading_stats(self, stats: Dict) -> str:
        return f"""
            <div class="metric">
                <span>Total Trades:</span>
                <span class="metric-value">{stats.get('total_trades', 0)}</span>
            </div>
            <div class="metric">
                <span>Win Rate:</span>
                <span class="metric-value positive">{stats.get('win_rate', 0)}%</span>
            </div>
            <div class="metric">
                <span>Total P&L:</span>
                <span class="metric-value {'positive' if stats.get('total_pnl', 0) >= 0 else 'negative'}">${stats.get('total_pnl', 0):+.2f}</span>
            </div>
            <div class="metric">
                <span>Average per Trade:</span>
                <span class="metric-value">${stats.get('avg_pnl', 0):+.2f}</span>
            </div>
        """


async def main():
    """Generate the new money-maker dashboard."""
    dashboard = MoneyMakerDashboard("data/whales.db")
    
    try:
        data = await dashboard.generate_dashboard_data()
        
        print("=== POLYMARKET MONEY MAKER DASHBOARD ===")
        print(f"Generated at: {data['generated_at']}")
        print(f"System status: {data['paper_trading_proof']['system_status']}")
        print(f"Data quality: {data['system_health']['data_quality']}")
        print(f"Resolution rate: {data['system_health']['resolution_rate']}%")
        print(f"Qualified whales: {data['overview']['qualified_whales']}")
        print(f"Active signals: {data['signals']['active_count']}")
        print(f"Paper trading P&L: ${data['paper_trading_proof']['total_pnl']:+.2f}")
        
        # Save data
        with open('money_maker_data.json', 'w') as f:
            json.dump(data, f, indent=2)
        
        print("\n=== Dashboard data saved to money_maker_data.json ===")
        
    finally:
        await dashboard.signals_generator.close()


if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())