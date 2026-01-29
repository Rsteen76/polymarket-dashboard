#!/usr/bin/env python3
"""
Paper Trading Tracker
Tracks the performance of alpha opportunities for theoretical P&L calculation
before deploying real capital.
"""

import json
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PaperTradingTracker:
    """Tracks paper trades and calculates theoretical performance"""
    
    def __init__(self):
        self.alpha_file = "/output/polymarket_alpha.json"
        self.paper_trades_file = "/output/paper_trades.json"
        self.seen_opportunities_file = "/data/seen_opportunities.json"
        self.bet_size = 100  # $100 per opportunity
        
    def load_seen_opportunities(self) -> set:
        """Load previously tracked opportunity IDs"""
        try:
            if os.path.exists(self.seen_opportunities_file):
                with open(self.seen_opportunities_file, 'r') as f:
                    return set(json.load(f))
        except Exception as e:
            logger.error(f"Error loading seen opportunities: {e}")
        return set()
    
    def save_seen_opportunities(self, seen_opps: set):
        """Save tracked opportunity IDs"""
        try:
            os.makedirs(os.path.dirname(self.seen_opportunities_file), exist_ok=True)
            with open(self.seen_opportunities_file, 'w') as f:
                json.dump(list(seen_opps), f)
        except Exception as e:
            logger.error(f"Error saving seen opportunities: {e}")
    
    def load_paper_trades(self) -> dict:
        """Load existing paper trades"""
        try:
            if os.path.exists(self.paper_trades_file):
                with open(self.paper_trades_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading paper trades: {e}")
        
        return {
            "trades": [],
            "performance": {
                "totalTrades": 0,
                "winRate": 0,
                "totalPnL": 0,
                "sharpeRatio": None,
                "maxDrawdown": 0,
                "startDate": None
            },
            "lastUpdate": None
        }
    
    def save_paper_trades(self, trades_data: dict):
        """Save paper trades to file"""
        try:
            os.makedirs(os.path.dirname(self.paper_trades_file), exist_ok=True)
            trades_data["lastUpdate"] = datetime.now().isoformat()
            
            with open(self.paper_trades_file, 'w') as f:
                json.dump(trades_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving paper trades: {e}")
    
    def get_market_price(self, market_id: str, direction: str) -> Optional[float]:
        """Get current market price for YES/NO outcome"""
        try:
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            market_data = response.json()
            outcomes = market_data.get("outcomes", [])
            
            target_slug = "yes" if direction.upper() == "YES" else "no"
            outcome = next((o for o in outcomes if o.get("slug") == target_slug), None)
            
            if outcome:
                return float(outcome.get("price", 0))
                
        except Exception as e:
            logger.error(f"Error fetching market price for {market_id}: {e}")
        
        return None
    
    def calculate_payout(self, bet_amount: float, entry_price: float, direction: str, actual_outcome: bool) -> float:
        """Calculate payout for a bet"""
        if direction.upper() == "YES":
            if actual_outcome:  # YES won
                return bet_amount / entry_price
            else:  # YES lost
                return 0
        else:  # NO bet
            if not actual_outcome:  # NO won (YES = False)
                return bet_amount / entry_price
            else:  # NO lost
                return 0
    
    def check_market_resolution(self, market_id: str) -> Optional[bool]:
        """Check if market is resolved and get the outcome"""
        try:
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            market_data = response.json()
            
            # Check if market is closed
            if not market_data.get("active", True):
                # Look for winning outcome
                outcomes = market_data.get("outcomes", [])
                for outcome in outcomes:
                    if outcome.get("winner", False):
                        return outcome.get("slug") == "yes"
            
        except Exception as e:
            logger.error(f"Error checking resolution for {market_id}: {e}")
        
        return None  # Not resolved yet
    
    def record_new_opportunities(self):
        """Record new alpha opportunities as paper trades"""
        try:
            # Load current alpha opportunities
            if not os.path.exists(self.alpha_file):
                return
            
            with open(self.alpha_file, 'r') as f:
                alpha_data = json.load(f)
            
            opportunities = alpha_data.get("opportunities", [])
            seen_opps = self.load_seen_opportunities()
            paper_trades = self.load_paper_trades()
            
            new_trades = 0
            
            for opp in opportunities:
                market_id = opp.get("market_id", "")
                if not market_id or market_id in seen_opps:
                    continue
                
                # Get current market price
                direction = opp.get("direction", "YES")
                entry_price = self.get_market_price(market_id, direction)
                
                if entry_price is None:
                    continue
                
                # Create paper trade
                trade = {
                    "id": f"{market_id}_{direction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "market_id": market_id,
                    "market": opp.get("market", ""),
                    "direction": direction,
                    "entry_price": entry_price,
                    "bet_amount": self.bet_size,
                    "entry_time": datetime.now().isoformat(),
                    "confidence": opp.get("confidence", "medium"),
                    "source": opp.get("source", "unknown"),
                    "edge": opp.get("edge", "0%"),
                    "expires": opp.get("expires", ""),
                    "resolved": False,
                    "outcome": None,
                    "payout": None,
                    "pnl": None
                }
                
                paper_trades["trades"].append(trade)
                seen_opps.add(market_id)
                new_trades += 1
                
                logger.info(f"Recorded paper trade: {trade['market']} - {direction} @ {entry_price}")
            
            if new_trades > 0:
                self.save_paper_trades(paper_trades)
                self.save_seen_opportunities(seen_opps)
                logger.info(f"Recorded {new_trades} new paper trades")
            
        except Exception as e:
            logger.error(f"Error recording new opportunities: {e}")
    
    def update_resolved_trades(self):
        """Check for resolved trades and update P&L"""
        try:
            paper_trades = self.load_paper_trades()
            trades = paper_trades.get("trades", [])
            
            updated = False
            
            for trade in trades:
                if trade.get("resolved", False):
                    continue
                
                market_id = trade.get("market_id")
                if not market_id:
                    continue
                
                # Check if market is resolved
                outcome = self.check_market_resolution(market_id)
                if outcome is not None:
                    # Market is resolved
                    trade["resolved"] = True
                    trade["outcome"] = outcome
                    
                    # Calculate payout and P&L
                    payout = self.calculate_payout(
                        trade["bet_amount"],
                        trade["entry_price"],
                        trade["direction"],
                        outcome
                    )
                    
                    trade["payout"] = payout
                    trade["pnl"] = payout - trade["bet_amount"]
                    
                    logger.info(f"Trade resolved: {trade['market']} - "
                              f"{'WIN' if trade['pnl'] > 0 else 'LOSS'} "
                              f"P&L: ${trade['pnl']:.2f}")
                    
                    updated = True
            
            if updated:
                self.update_performance_metrics(paper_trades)
                self.save_paper_trades(paper_trades)
                logger.info("Updated resolved trades and performance metrics")
            
        except Exception as e:
            logger.error(f"Error updating resolved trades: {e}")
    
    def update_performance_metrics(self, paper_trades: dict):
        """Calculate and update performance metrics"""
        trades = paper_trades.get("trades", [])
        resolved_trades = [t for t in trades if t.get("resolved", False)]
        
        if not resolved_trades:
            return
        
        # Basic metrics
        total_trades = len(resolved_trades)
        wins = len([t for t in resolved_trades if t.get("pnl", 0) > 0])
        win_rate = wins / total_trades if total_trades > 0 else 0
        total_pnl = sum(t.get("pnl", 0) for t in resolved_trades)
        
        # Start date
        start_date = None
        if resolved_trades:
            start_date = min(t.get("entry_time", "") for t in resolved_trades)
        
        # Running P&L for drawdown calculation
        pnls = [t.get("pnl", 0) for t in sorted(resolved_trades, key=lambda x: x.get("entry_time", ""))]
        running_pnl = []
        cumulative = 0
        for pnl in pnls:
            cumulative += pnl
            running_pnl.append(cumulative)
        
        # Max drawdown
        peak = running_pnl[0] if running_pnl else 0
        max_drawdown = 0
        
        for pnl in running_pnl:
            if pnl > peak:
                peak = pnl
            drawdown = peak - pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Sharpe ratio (simplified)
        if len(pnls) > 1:
            avg_return = sum(pnls) / len(pnls)
            variance = sum((pnl - avg_return) ** 2 for pnl in pnls) / len(pnls)
            std_dev = variance ** 0.5
            sharpe_ratio = avg_return / std_dev if std_dev > 0 else None
        else:
            sharpe_ratio = None
        
        # Update performance
        paper_trades["performance"] = {
            "totalTrades": total_trades,
            "winRate": win_rate,
            "totalPnL": total_pnl,
            "sharpeRatio": sharpe_ratio,
            "maxDrawdown": max_drawdown,
            "startDate": start_date
        }
        
        # Update the alpha data with performance
        try:
            if os.path.exists(self.alpha_file):
                with open(self.alpha_file, 'r') as f:
                    alpha_data = json.load(f)
                
                alpha_data["performance"] = {
                    "paperTrades": total_trades,
                    "wins": wins,
                    "losses": total_trades - wins,
                    "theoreticalPnL": total_pnl
                }
                
                with open(self.alpha_file, 'w') as f:
                    json.dump(alpha_data, f, indent=2)
                    
        except Exception as e:
            logger.error(f"Error updating alpha performance: {e}")
    
    def run_tracking_update(self):
        """Main tracking update - record new trades and check resolutions"""
        logger.info("=== Paper Trading Tracker Update ===")
        
        try:
            self.record_new_opportunities()
            self.update_resolved_trades()
            
            # Log current status
            paper_trades = self.load_paper_trades()
            perf = paper_trades.get("performance", {})
            
            logger.info(f"Total paper trades: {perf.get('totalTrades', 0)}")
            logger.info(f"Win rate: {perf.get('winRate', 0):.1%}")
            logger.info(f"Total P&L: ${perf.get('totalPnL', 0):.2f}")
            
            logger.info("=== Tracker update complete ===")
            
        except Exception as e:
            logger.error(f"Error in tracking update: {e}")

if __name__ == "__main__":
    tracker = PaperTradingTracker()
    tracker.run_tracking_update()