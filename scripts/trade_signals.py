#!/usr/bin/env python3
"""
TRADE SIGNALS - Actionable Whale Tracking

Identifies high-confidence trade opportunities based on proven whale performance.
This is where the money gets made.
"""

import sqlite3
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"


class TradeSignalsGenerator:
    """Generates actionable trade signals based on proven whale performance."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.session = None
        
        # Signal criteria
        self.MIN_WIN_RATE = 60.0  # 60%+ win rate required
        self.MIN_RESOLVED_TRADES = 20  # 20+ resolved trades for credibility
        self.MIN_ROI = 10.0  # 10%+ ROI required
        self.RECENT_HOURS = 24  # Trades within last 24 hours
        
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"Accept": "application/json"}
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    def get_proven_whales(self) -> List[Dict]:
        """Get whales that meet our criteria for generating signals."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Get whales with performance data
        c.execute("""
            SELECT 
                w.address,
                COUNT(CASE WHEN t.resolved = 1 THEN 1 END) as resolved_trades,
                COUNT(CASE WHEN t.outcome = 'WIN' THEN 1 END) as wins,
                COUNT(CASE WHEN t.outcome = 'LOSS' THEN 1 END) as losses,
                SUM(CASE WHEN t.resolved = 1 THEN t.pnl ELSE 0 END) as total_pnl,
                SUM(CASE WHEN t.resolved = 1 THEN t.size ELSE 0 END) as total_wagered
            FROM whales w
            LEFT JOIN trades t ON w.address = t.whale_address
            GROUP BY w.address
            HAVING resolved_trades >= ?
        """, (self.MIN_RESOLVED_TRADES,))
        
        whales = []
        for row in c.fetchall():
            resolved_trades = row['resolved_trades']
            wins = row['wins'] or 0
            losses = row['losses'] or 0
            total_pnl = row['total_pnl'] or 0
            total_wagered = row['total_wagered'] or 0
            
            if resolved_trades > 0:
                win_rate = (wins / resolved_trades) * 100
                roi = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0
                
                if win_rate >= self.MIN_WIN_RATE and roi >= self.MIN_ROI:
                    whales.append({
                        'address': row['address'],
                        'resolved_trades': resolved_trades,
                        'win_rate': round(win_rate, 1),
                        'roi': round(roi, 1),
                        'total_pnl': round(total_pnl, 2),
                        'wins': wins,
                        'losses': losses
                    })
        
        conn.close()
        
        # Sort by ROI
        whales.sort(key=lambda x: x['roi'], reverse=True)
        return whales
    
    def get_recent_trades(self, whale_address: str, hours: int = 24) -> List[Dict]:
        """Get recent unresolved trades from a whale."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        c.execute("""
            SELECT market_id, market_question, side, size, entry_price, entry_time
            FROM trades
            WHERE whale_address = ?
            AND datetime(entry_time) >= datetime(?)
            AND (resolved = 0 OR resolved IS NULL)
            ORDER BY entry_time DESC
        """, (whale_address, cutoff_time.isoformat()))
        
        trades = [dict(row) for row in c.fetchall()]
        conn.close()
        return trades
    
    async def get_current_market_price(self, market_id: str) -> Optional[Dict]:
        """Get current YES/NO prices for a market."""
        await self._ensure_session()
        
        try:
            url = f"{GAMMA_API_BASE}/markets"
            params = {"condition_id": market_id}
            
            async with self.session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        market = data[0]
                        outcome_prices = market.get('outcomePrices', [])
                        
                        if outcome_prices and len(outcome_prices) >= 2:
                            return {
                                "yes_price": float(outcome_prices[0]),
                                "no_price": float(outcome_prices[1]),
                                "active": market.get('active', False),
                                "resolved": market.get('resolved', False)
                            }
        except Exception as e:
            logger.debug(f"Error fetching price for {market_id}: {e}")
        
        return None
    
    def calculate_edge(self, whale_win_rate: float, whale_roi: float, current_price: float, direction: str) -> float:
        """
        Estimate edge based on whale's historical performance.
        This is simplified - a proper model would be more complex.
        """
        # Convert whale performance to implied probability
        base_prob = whale_win_rate / 100.0
        
        # Adjust for ROI (higher ROI suggests better edge detection)
        roi_multiplier = min(1.5, 1.0 + (whale_roi / 100.0))
        adjusted_prob = min(0.95, base_prob * roi_multiplier)
        
        # Compare to market price
        if direction.upper() == "YES":
            market_implied_prob = current_price
            edge = (adjusted_prob - market_implied_prob) / market_implied_prob * 100
        else:  # NO
            market_implied_prob = 1 - current_price
            edge = (adjusted_prob - market_implied_prob) / market_implied_prob * 100
        
        return round(edge, 1)
    
    async def generate_signals(self) -> List[Dict]:
        """Generate all current trade signals."""
        proven_whales = self.get_proven_whales()
        signals = []
        
        logger.info(f"Checking {len(proven_whales)} proven whales for signals...")
        
        for whale in proven_whales:
            whale_address = whale['address']
            recent_trades = self.get_recent_trades(whale_address, self.RECENT_HOURS)
            
            for trade in recent_trades:
                market_id = trade['market_id']
                if not market_id:
                    continue
                
                # Get current market price
                price_data = await self.get_current_market_price(market_id)
                if not price_data or not price_data.get('active', False):
                    continue
                
                direction = trade['side'].upper() if trade['side'] else 'YES'
                current_price = price_data['yes_price'] if direction == 'YES' else price_data['no_price']
                whale_entry = float(trade['entry_price'] or 0.5)
                
                # Calculate edge
                edge = self.calculate_edge(whale['win_rate'], whale['roi'], current_price, direction)
                
                # Only include if positive edge and reasonable price difference
                if edge > 5:  # At least 5% edge
                    signal = {
                        "signal_id": f"{whale_address[:10]}_{market_id}_{direction}",
                        "market_id": market_id,
                        "market_question": trade['market_question'],
                        "direction": direction,
                        "whale_address": whale_address,
                        "whale_stats": {
                            "win_rate": whale['win_rate'],
                            "resolved_trades": whale['resolved_trades'],
                            "total_pnl": whale['total_pnl'],
                            "roi": whale['roi']
                        },
                        "price_data": {
                            "whale_entry": whale_entry,
                            "current_yes": price_data['yes_price'],
                            "current_no": price_data['no_price'],
                            "recommended_price": current_price
                        },
                        "edge_estimate": edge,
                        "trade_time": trade['entry_time'],
                        "trade_size": trade['size'],
                        "confidence": self._calculate_confidence(whale, edge),
                        "generated_at": datetime.now().isoformat()
                    }
                    signals.append(signal)
                
                # Rate limit
                await asyncio.sleep(0.3)
        
        # Sort by edge estimate
        signals.sort(key=lambda x: x['edge_estimate'], reverse=True)
        return signals
    
    def _calculate_confidence(self, whale: Dict, edge: float) -> str:
        """Calculate confidence level for a signal."""
        score = 0
        
        # Win rate contribution
        if whale['win_rate'] >= 70:
            score += 3
        elif whale['win_rate'] >= 65:
            score += 2
        else:
            score += 1
        
        # Sample size contribution
        if whale['resolved_trades'] >= 50:
            score += 3
        elif whale['resolved_trades'] >= 30:
            score += 2
        else:
            score += 1
        
        # Edge contribution
        if edge >= 20:
            score += 3
        elif edge >= 15:
            score += 2
        else:
            score += 1
        
        if score >= 8:
            return "HIGH"
        elif score >= 6:
            return "MEDIUM"
        else:
            return "LOW"
    
    async def detect_consensus_signals(self, signals: List[Dict]) -> List[Dict]:
        """Find markets where multiple proven whales agree."""
        # Group signals by market and direction
        market_positions = {}
        
        for signal in signals:
            market_id = signal['market_id']
            direction = signal['direction']
            key = f"{market_id}_{direction}"
            
            if key not in market_positions:
                market_positions[key] = {
                    'market_id': market_id,
                    'market_question': signal['market_question'],
                    'direction': direction,
                    'whales': [],
                    'total_edge': 0,
                    'avg_win_rate': 0,
                    'total_resolved_trades': 0
                }
            
            market_positions[key]['whales'].append({
                'address': signal['whale_address'],
                'win_rate': signal['whale_stats']['win_rate'],
                'resolved_trades': signal['whale_stats']['resolved_trades'],
                'edge': signal['edge_estimate']
            })
            market_positions[key]['total_edge'] += signal['edge_estimate']
        
        # Find consensus (2+ whales on same side)
        consensus_signals = []
        for key, position in market_positions.items():
            if len(position['whales']) >= 2:
                position['avg_win_rate'] = sum(w['win_rate'] for w in position['whales']) / len(position['whales'])
                position['total_resolved_trades'] = sum(w['resolved_trades'] for w in position['whales'])
                position['avg_edge'] = position['total_edge'] / len(position['whales'])
                position['whale_count'] = len(position['whales'])
                position['consensus_confidence'] = self._calculate_consensus_confidence(position)
                
                consensus_signals.append(position)
        
        # Sort by confidence and edge
        consensus_signals.sort(key=lambda x: (x['avg_edge'], x['avg_win_rate']), reverse=True)
        return consensus_signals
    
    def _calculate_consensus_confidence(self, position: Dict) -> str:
        """Calculate confidence for consensus signals."""
        whale_count = position['whale_count']
        avg_win_rate = position['avg_win_rate']
        avg_edge = position['avg_edge']
        total_trades = position['total_resolved_trades']
        
        score = 0
        score += min(4, whale_count)  # More whales = higher confidence
        score += 3 if avg_win_rate >= 70 else 2 if avg_win_rate >= 65 else 1
        score += 3 if avg_edge >= 20 else 2 if avg_edge >= 15 else 1
        score += 2 if total_trades >= 100 else 1
        
        if score >= 10:
            return "VERY HIGH"
        elif score >= 8:
            return "HIGH"
        elif score >= 6:
            return "MEDIUM"
        else:
            return "LOW"


async def main():
    """Generate trade signals report."""
    generator = TradeSignalsGenerator("data/whales.db")
    
    try:
        print("=== GENERATING TRADE SIGNALS ===")
        
        # Generate individual signals
        signals = await generator.generate_signals()
        print(f"Found {len(signals)} individual signals")
        
        # Detect consensus
        consensus = await generator.detect_consensus_signals(signals)
        print(f"Found {len(consensus)} consensus signals")
        
        # Create report
        report = {
            "generated_at": datetime.now().isoformat(),
            "criteria": {
                "min_win_rate": generator.MIN_WIN_RATE,
                "min_resolved_trades": generator.MIN_RESOLVED_TRADES,
                "min_roi": generator.MIN_ROI,
                "recent_hours": generator.RECENT_HOURS
            },
            "summary": {
                "individual_signals": len(signals),
                "consensus_signals": len(consensus),
                "high_confidence_signals": len([s for s in signals if s['confidence'] == 'HIGH']),
                "very_high_consensus": len([c for c in consensus if c['consensus_confidence'] == 'VERY HIGH'])
            },
            "signals": signals[:20],  # Top 20
            "consensus": consensus,
            "all_signals": signals
        }
        
        # Save report
        with open('trade_signals.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print("\n=== TOP SIGNALS ===")
        for i, signal in enumerate(signals[:5]):
            print(f"\n{i+1}. {signal['direction']} - {signal['market_question'][:60]}...")
            print(f"   Whale: {signal['whale_address'][:10]}... ({signal['whale_stats']['win_rate']}% WR, {signal['whale_stats']['resolved_trades']} trades)")
            print(f"   Edge: {signal['edge_estimate']:+.1f}% | Price: ${signal['price_data']['recommended_price']:.3f} | Confidence: {signal['confidence']}")
        
        if consensus:
            print("\n=== CONSENSUS SIGNALS ===")
            for i, cons in enumerate(consensus[:3]):
                print(f"\n{i+1}. {cons['direction']} - {cons['market_question'][:60]}...")
                print(f"   {cons['whale_count']} whales agree | Avg edge: {cons['avg_edge']:+.1f}% | Confidence: {cons['consensus_confidence']}")
                for whale in cons['whales']:
                    print(f"     - {whale['address'][:10]}... ({whale['win_rate']:.1f}% WR, {whale['edge']:+.1f}% edge)")
        
        print(f"\n=== Signals saved to trade_signals.json ===")
        
    finally:
        await generator.close()


if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())