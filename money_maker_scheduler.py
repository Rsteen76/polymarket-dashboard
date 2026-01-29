#!/usr/bin/env python3
"""
MONEY MAKER SCHEDULER

Orchestrates all components of the money-making system:
1. Resolution checking (backfill and updates)
2. Signal generation
3. Paper trading execution  
4. Dashboard update
5. Performance tracking

Run this hourly to keep the system updated.
"""

import asyncio
import logging
import subprocess
import sys
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add scripts to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from resolution_checker import ResolutionChecker
from new_scoring_system import PerformanceAnalyzer
from trade_signals import TradeSignalsGenerator
from enhanced_paper_trading import PaperTradingSystem
from new_dashboard import MoneyMakerDashboard
from weather_arbitrage import get_weather_arbitrage_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MoneyMakerScheduler:
    """Orchestrates all money-maker components."""
    
    def __init__(self, db_path: str = "data/whales.db"):
        self.db_path = db_path
        self.resolution_checker = ResolutionChecker(db_path)
        self.performance_analyzer = PerformanceAnalyzer(db_path)
        self.signals_generator = TradeSignalsGenerator(db_path)
        self.paper_trading = PaperTradingSystem(db_path)
        self.dashboard = MoneyMakerDashboard(db_path)
        
    async def run_complete_update(self, quick_mode: bool = False) -> Dict:
        """Run a complete system update."""
        logger.info("=== MONEY MAKER SYSTEM UPDATE START ===")
        start_time = datetime.now()
        
        results = {
            "started_at": start_time.isoformat(),
            "quick_mode": quick_mode,
            "steps": {}
        }
        
        try:
            # Step 1: Resolution checking
            logger.info("Step 1/5: Checking market resolutions...")
            try:
                if quick_mode:
                    # Quick mode: only check markets with recent trades
                    resolution_summary = await self._quick_resolution_check()
                else:
                    # Full mode: check all unresolved markets
                    resolution_summary = await self.resolution_checker.check_all_unresolved(verbose=True)
                
                results["steps"]["resolution_check"] = {
                    "status": "completed",
                    "markets_checked": resolution_summary.get("markets_checked", 0),
                    "markets_resolved": resolution_summary.get("markets_resolved", 0),
                    "trades_resolved": resolution_summary.get("total_trades_resolved", 0),
                    "total_pnl": resolution_summary.get("total_pnl", 0)
                }
                
                logger.info(f"Resolved {resolution_summary.get('markets_resolved', 0)} markets, "
                           f"{resolution_summary.get('total_trades_resolved', 0)} trades")
                
            except Exception as e:
                logger.error(f"Resolution check failed: {e}")
                results["steps"]["resolution_check"] = {"status": "failed", "error": str(e)}
            
            # Step 2: Performance analysis
            logger.info("Step 2/5: Analyzing whale performance...")
            try:
                performance_report = self.performance_analyzer.generate_performance_report()
                
                results["steps"]["performance_analysis"] = {
                    "status": "completed", 
                    "qualified_whales": len(performance_report.get("top_performers", [])),
                    "total_resolved_trades": performance_report.get("summary", {}).get("total_resolved_trades", 0)
                }
                
                # Save performance report
                with open('performance_report.json', 'w') as f:
                    json.dump(performance_report, f, indent=2)
                    
                logger.info(f"Analyzed {results['steps']['performance_analysis']['qualified_whales']} qualified whales")
                
            except Exception as e:
                logger.error(f"Performance analysis failed: {e}")
                results["steps"]["performance_analysis"] = {"status": "failed", "error": str(e)}
            
            # Step 3: Signal generation
            logger.info("Step 3/5: Generating trade signals...")
            try:
                signals = await self.signals_generator.generate_signals()
                consensus_signals = await self.signals_generator.detect_consensus_signals(signals)
                
                results["steps"]["signal_generation"] = {
                    "status": "completed",
                    "signals_generated": len(signals),
                    "consensus_signals": len(consensus_signals),
                    "high_confidence": len([s for s in signals if s.get('confidence') == 'HIGH'])
                }
                
                # Save signals
                signals_data = {
                    "generated_at": datetime.now().isoformat(),
                    "signals": signals,
                    "consensus": consensus_signals,
                    "summary": results["steps"]["signal_generation"]
                }
                
                with open('trade_signals.json', 'w') as f:
                    json.dump(signals_data, f, indent=2)
                    
                logger.info(f"Generated {len(signals)} signals, {len(consensus_signals)} consensus")
                
            except Exception as e:
                logger.error(f"Signal generation failed: {e}")
                results["steps"]["signal_generation"] = {"status": "failed", "error": str(e)}
                signals_data = {"signals": [], "consensus": []}
            
            # Step 4: Paper trading execution
            logger.info("Step 4/5: Executing paper trades...")
            try:
                # Process new signals as paper trades
                new_paper_trades = self.paper_trading.process_new_signals('trade_signals.json')
                
                # Check for resolutions
                resolved_paper_trades = self.paper_trading.check_paper_trade_resolutions()
                
                # Get performance
                performance = self.paper_trading.get_performance_summary(30)
                system_proof = self.paper_trading.get_system_proof()
                
                results["steps"]["paper_trading"] = {
                    "status": "completed",
                    "new_trades": new_paper_trades,
                    "resolved_trades": resolved_paper_trades,
                    "total_trades": system_proof.get("total_paper_trades", 0),
                    "win_rate": system_proof.get("win_rate", 0),
                    "total_pnl": system_proof.get("total_pnl", 0)
                }
                
                logger.info(f"Paper trading: {new_paper_trades} new, {resolved_paper_trades} resolved, "
                           f"{system_proof.get('win_rate', 0)}% WR on {system_proof.get('total_paper_trades', 0)} trades")
                
            except Exception as e:
                logger.error(f"Paper trading failed: {e}")
                results["steps"]["paper_trading"] = {"status": "failed", "error": str(e)}
            
            # Step 5: Dashboard generation
            logger.info("Step 5/6: Updating dashboard...")
            try:
                dashboard_data = await self.dashboard.generate_dashboard_data()
                
                # Generate HTML dashboard
                await self.dashboard.generate_html_dashboard('money_maker_dashboard.html')
                
                results["steps"]["dashboard_update"] = {
                    "status": "completed",
                    "data_quality": dashboard_data.get("system_health", {}).get("data_quality", "Unknown"),
                    "resolution_rate": dashboard_data.get("system_health", {}).get("resolution_rate", 0),
                    "system_status": dashboard_data.get("paper_trading_proof", {}).get("system_status", "Unknown")
                }
                
                logger.info(f"Dashboard updated - Status: {results['steps']['dashboard_update']['system_status']}")
                
            except Exception as e:
                logger.error(f"Dashboard update failed: {e}")
                results["steps"]["dashboard_update"] = {"status": "failed", "error": str(e)}
            
            # Step 6: Weather arbitrage scan
            logger.info("Step 6/6: Scanning weather arbitrage...")
            try:
                weather_data = get_weather_arbitrage_data()
                
                # Save weather data
                with open('weather_data.json', 'w') as f:
                    json.dump(weather_data, f, indent=2)
                
                results["steps"]["weather_arbitrage"] = {
                    "status": "completed",
                    "opportunities": weather_data.get("summary", {}).get("total_opportunities", 0),
                    "strong_signals": weather_data.get("summary", {}).get("strong_signals", 0),
                    "avg_edge": weather_data.get("summary", {}).get("avg_edge", 0)
                }
                
                logger.info(f"Weather arbitrage: {results['steps']['weather_arbitrage']['opportunities']} opportunities, "
                           f"{results['steps']['weather_arbitrage']['strong_signals']} strong signals")
                
            except Exception as e:
                logger.error(f"Weather arbitrage scan failed: {e}")
                results["steps"]["weather_arbitrage"] = {"status": "failed", "error": str(e)}
            
        finally:
            # Clean up async resources
            try:
                await self.resolution_checker.close()
                await self.signals_generator.close()
            except:
                pass
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        results["completed_at"] = end_time.isoformat()
        results["duration_seconds"] = round(duration, 2)
        results["success"] = all(step.get("status") == "completed" for step in results["steps"].values())
        
        logger.info(f"=== MONEY MAKER UPDATE COMPLETE ({duration:.1f}s) - Success: {results['success']} ===")
        
        # Save update log
        with open('last_update.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        return results
    
    async def _quick_resolution_check(self) -> Dict:
        """Quick resolution check - only recent markets."""
        # Get markets from trades in last 48 hours
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        c.execute("""
            SELECT DISTINCT market_id 
            FROM trades 
            WHERE (resolved = 0 OR resolved IS NULL) 
            AND entry_time >= ?
            LIMIT 100
        """, (cutoff,))
        
        recent_markets = [row[0] for row in c.fetchall()]
        conn.close()
        
        logger.info(f"Quick mode: checking {len(recent_markets)} recent markets")
        
        # Check only these markets
        summary = {
            "markets_checked": len(recent_markets),
            "markets_resolved": 0,
            "total_trades_resolved": 0,
            "total_pnl": 0,
            "resolutions": []
        }
        
        for market_id in recent_markets:
            resolution = await self.resolution_checker.check_market_resolution(market_id)
            if resolution:
                result = self.resolution_checker.resolve_market_trades(market_id, resolution["winner"])
                summary["markets_resolved"] += 1
                summary["total_trades_resolved"] += result["trades_resolved"]
                summary["total_pnl"] += result["total_pnl"]
                
            await asyncio.sleep(0.5)  # Rate limit
        
        return summary


async def main():
    """Main scheduler entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Money Maker System Scheduler")
    parser.add_argument("--quick", action="store_true", help="Quick mode (recent markets only)")
    parser.add_argument("--db", default="data/whales.db", help="Database path")
    args = parser.parse_args()
    
    scheduler = MoneyMakerScheduler(args.db)
    
    try:
        results = await scheduler.run_complete_update(quick_mode=args.quick)
        
        # Print summary
        print("\n=== SYSTEM UPDATE SUMMARY ===")
        print(f"Duration: {results['duration_seconds']:.1f} seconds")
        print(f"Success: {results['success']}")
        
        for step_name, step_data in results["steps"].items():
            status = step_data.get("status", "unknown")
            print(f"{step_name}: {status.upper()}")
            
            if status == "completed":
                if step_name == "resolution_check":
                    print(f"  - Resolved {step_data['markets_resolved']} markets, {step_data['trades_resolved']} trades")
                elif step_name == "signal_generation":
                    print(f"  - Generated {step_data['signals_generated']} signals, {step_data['high_confidence']} high confidence")
                elif step_name == "paper_trading":
                    print(f"  - {step_data['new_trades']} new trades, {step_data['win_rate']}% WR, ${step_data['total_pnl']:+.2f} P&L")
                elif step_name == "dashboard_update":
                    print(f"  - Status: {step_data['system_status']}, Resolution rate: {step_data['resolution_rate']}%")
            elif status == "failed":
                print(f"  - Error: {step_data.get('error', 'Unknown error')}")
        
        if not results['success']:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Scheduler failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())