#!/usr/bin/env python3
"""
Polymarket Alpha Scanner
Continuously scans for arbitrage opportunities across weather markets, 
whale consensus, and new market launches.
"""

import requests
import json
import time
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import sys
import os
from dataclasses import dataclass, asdict
import schedule
import threading
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class AlphaOpportunity:
    """Represents a detected alpha opportunity"""
    market: str
    market_id: str
    edge: str  # e.g. "35%"
    direction: str  # "YES" or "NO"
    confidence: str  # "high", "medium", "low"
    expires: str  # ISO timestamp
    source: str  # "weather", "whale", "new_market"
    market_url: str = ""
    current_price: float = 0.0
    true_probability: float = 0.0
    volume_24h: float = 0.0
    reasoning: str = ""

class WeatherArbitrageScanner:
    """Scans weather markets for mispricings vs real forecasts"""
    
    def __init__(self):
        self.cities = [
            {"name": "New York", "lat": 40.7128, "lon": -74.0060},
            {"name": "London", "lat": 51.5074, "lon": -0.1278},
            {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
            {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437}
        ]
    
    def get_weather_forecast(self, city: dict) -> Optional[dict]:
        """Get weather forecast from Open-Meteo API"""
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": city["lat"],
                "longitude": city["lon"],
                "hourly": "temperature_2m,precipitation_probability,precipitation",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "forecast_days": 7
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching weather for {city['name']}: {e}")
            return None
    
    def get_weather_markets(self) -> List[dict]:
        """Get weather-related markets from Polymarket"""
        try:
            url = "https://gamma-api.polymarket.com/markets"
            params = {
                "limit": 100,
                "closed": "false"
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Filter for weather-related markets
            weather_markets = []
            weather_keywords = ["temperature", "rain", "snow", "weather", "celsius", "fahrenheit", "hot", "cold"]

            # Handle both list response and dict with "data" key
            markets_list = data if isinstance(data, list) else data.get("data", [])
            for market in markets_list:
                question = market.get("question", "").lower()
                if any(keyword in question for keyword in weather_keywords):
                    weather_markets.append(market)
            
            return weather_markets
        except Exception as e:
            logger.error(f"Error fetching Polymarket weather markets: {e}")
            return []
    
    def analyze_temperature_market(self, market: dict, forecasts: dict) -> Optional[AlphaOpportunity]:
        """Analyze a temperature market for arbitrage opportunities"""
        question = market.get("question", "")
        
        # Extract temperature threshold and city from question
        # Example: "Will New York City reach 80°F on January 30?"
        import re
        
        # Extract temperature
        temp_match = re.search(r'(\d+)°?[FfCc]', question)
        if not temp_match:
            return None
        
        threshold_temp = float(temp_match.group(1))
        
        # Extract city
        city_name = None
        for city in self.cities:
            if city["name"].lower() in question.lower():
                city_name = city["name"]
                break
        
        if not city_name:
            return None
        
        # Get forecast for this city
        city_forecast = None
        for city in self.cities:
            if city["name"] == city_name:
                city_forecast = self.get_weather_forecast(city)
                break
        
        if not city_forecast:
            return None
        
        # Calculate probability of reaching threshold
        daily = city_forecast.get("daily", {})
        max_temps = daily.get("temperature_2m_max", [])
        
        if not max_temps:
            return None
        
        # For simplicity, check if max temp today/tomorrow exceeds threshold
        prob_exceed = 0.0
        for temp in max_temps[:3]:  # Next 3 days
            if temp >= threshold_temp:
                prob_exceed = max(prob_exceed, 0.9)  # High confidence if forecast shows it
            elif temp >= threshold_temp - 5:  # Close to threshold
                prob_exceed = max(prob_exceed, 0.3)  # Some chance
        
        # Get current market price
        outcomes = market.get("outcomes", [])
        yes_outcome = next((o for o in outcomes if o.get("slug") == "yes"), None)
        
        if not yes_outcome:
            return None
        
        current_price = float(yes_outcome.get("price", 0))
        
        # Calculate edge
        edge = prob_exceed - current_price
        
        if abs(edge) > 0.15:  # >15% edge threshold
            direction = "YES" if edge > 0 else "NO"
            confidence = "high" if abs(edge) > 0.3 else "medium"
            
            expires_str = market.get("endDate", "")
            if expires_str:
                expires = datetime.fromisoformat(expires_str.replace('Z', '+00:00')).isoformat()
            else:
                expires = (datetime.now() + timedelta(days=1)).isoformat()
            
            return AlphaOpportunity(
                market=question,
                market_id=market.get("id", ""),
                edge=f"{abs(edge):.1%}",
                direction=direction,
                confidence=confidence,
                expires=expires,
                source="weather",
                market_url=f"https://polymarket.com/market/{market.get('slug', '')}",
                current_price=current_price,
                true_probability=prob_exceed,
                volume_24h=float(market.get("volume24hr", 0)),
                reasoning=f"Forecast shows {prob_exceed:.1%} chance vs market {current_price:.1%}"
            )
        
        return None
    
    def scan(self) -> List[AlphaOpportunity]:
        """Scan for weather arbitrage opportunities"""
        logger.info("Starting weather arbitrage scan...")
        opportunities = []
        
        try:
            # Get weather markets
            weather_markets = self.get_weather_markets()
            logger.info(f"Found {len(weather_markets)} weather markets")
            
            # Get forecasts for all cities
            city_forecasts = {}
            for city in self.cities:
                forecast = self.get_weather_forecast(city)
                if forecast:
                    city_forecasts[city["name"]] = forecast
            
            # Analyze each market
            for market in weather_markets:
                opportunity = self.analyze_temperature_market(market, city_forecasts)
                if opportunity:
                    opportunities.append(opportunity)
                    logger.info(f"Found weather opportunity: {opportunity.market} - {opportunity.edge} edge")
            
        except Exception as e:
            logger.error(f"Error in weather scan: {e}")
        
        return opportunities

class WhaleConsensusScanner:
    """Scans for markets where multiple skilled whales agree"""
    
    def __init__(self, db_path: str = "/data/whales.db"):
        self.db_path = db_path
    
    def get_skilled_whales(self) -> List[str]:
        """Get addresses of whales with good win rates"""
        try:
            if not os.path.exists(self.db_path):
                logger.warning(f"Whale database not found: {self.db_path}")
                return []
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT address, win_count, loss_count 
                FROM whales 
                WHERE win_count + loss_count >= 10
            """)
            
            skilled_whales = []
            for row in cursor.fetchall():
                address, wins, losses = row
                win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
                
                if win_rate >= 0.65:  # 65%+ win rate
                    skilled_whales.append(address)
            
            conn.close()
            logger.info(f"Found {len(skilled_whales)} skilled whales")
            return skilled_whales
            
        except Exception as e:
            logger.error(f"Error getting skilled whales: {e}")
            return []
    
    def get_recent_whale_positions(self, whale_addresses: List[str]) -> Dict[str, List[dict]]:
        """Get recent positions for skilled whales"""
        try:
            if not os.path.exists(self.db_path):
                return {}
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get trades from last 24 hours
            since = datetime.now() - timedelta(hours=24)
            
            placeholders = ','.join(['?'] * len(whale_addresses))
            cursor.execute(f"""
                SELECT whale_address, market_id, market_question, side, size, entry_time
                FROM trades 
                WHERE whale_address IN ({placeholders})
                AND entry_time > ?
                AND resolved = FALSE
                ORDER BY entry_time DESC
            """, whale_addresses + [since])
            
            positions_by_market = defaultdict(list)
            for row in cursor.fetchall():
                whale, market_id, question, side, size, entry_time = row
                positions_by_market[market_id].append({
                    "whale": whale,
                    "question": question,
                    "side": side,
                    "size": size,
                    "entry_time": entry_time
                })
            
            conn.close()
            return dict(positions_by_market)
            
        except Exception as e:
            logger.error(f"Error getting whale positions: {e}")
            return {}
    
    def scan(self) -> List[AlphaOpportunity]:
        """Scan for whale consensus opportunities"""
        logger.info("Starting whale consensus scan...")
        opportunities = []
        
        try:
            skilled_whales = self.get_skilled_whales()
            if not skilled_whales:
                return opportunities
            
            positions = self.get_recent_whale_positions(skilled_whales)
            
            # Find markets with consensus (3+ whales on same side)
            for market_id, market_positions in positions.items():
                if len(market_positions) < 3:
                    continue
                
                # Group by side
                yes_whales = [p for p in market_positions if p["side"].upper() == "YES"]
                no_whales = [p for p in market_positions if p["side"].upper() == "NO"]
                
                consensus_side = None
                consensus_count = 0
                
                if len(yes_whales) >= 3:
                    consensus_side = "YES"
                    consensus_count = len(yes_whales)
                elif len(no_whales) >= 3:
                    consensus_side = "NO"
                    consensus_count = len(no_whales)
                
                if consensus_side and consensus_count >= 3:
                    # Get market data from Polymarket
                    try:
                        market_url = f"https://gamma-api.polymarket.com/markets/{market_id}"
                        response = requests.get(market_url, timeout=10)
                        
                        if response.status_code == 200:
                            market_data = response.json()
                            question = market_data.get("question", "Unknown market")
                            end_date = market_data.get("endDate", "")
                            
                            expires = datetime.fromisoformat(end_date.replace('Z', '+00:00')).isoformat() if end_date else ""
                            
                            confidence = "high" if consensus_count >= 5 else "medium"
                            
                            opportunity = AlphaOpportunity(
                                market=question,
                                market_id=market_id,
                                edge="25%",  # Estimated based on whale skill
                                direction=consensus_side,
                                confidence=confidence,
                                expires=expires,
                                source="whale",
                                market_url=f"https://polymarket.com/market/{market_data.get('slug', '')}",
                                reasoning=f"{consensus_count} skilled whales agree on {consensus_side}"
                            )
                            
                            opportunities.append(opportunity)
                            logger.info(f"Found whale consensus: {question} - {consensus_count} whales on {consensus_side}")
                    
                    except Exception as e:
                        logger.error(f"Error fetching market data for {market_id}: {e}")
            
        except Exception as e:
            logger.error(f"Error in whale consensus scan: {e}")
        
        return opportunities

class NewMarketScanner:
    """Scans for newly launched markets for early entry"""
    
    def __init__(self, lookback_hours: int = 2):
        self.lookback_hours = lookback_hours
        self.seen_markets_file = "/data/seen_markets.json"
        self.seen_markets = self.load_seen_markets()
    
    def load_seen_markets(self) -> set:
        """Load previously seen market IDs"""
        try:
            if os.path.exists(self.seen_markets_file):
                with open(self.seen_markets_file, 'r') as f:
                    return set(json.load(f))
        except Exception as e:
            logger.error(f"Error loading seen markets: {e}")
        return set()
    
    def save_seen_markets(self):
        """Save seen market IDs to disk"""
        try:
            os.makedirs(os.path.dirname(self.seen_markets_file), exist_ok=True)
            with open(self.seen_markets_file, 'w') as f:
                json.dump(list(self.seen_markets), f)
        except Exception as e:
            logger.error(f"Error saving seen markets: {e}")
    
    def scan(self) -> List[AlphaOpportunity]:
        """Scan for new market opportunities"""
        logger.info("Starting new market scan...")
        opportunities = []
        
        try:
            # Get recent markets
            url = "https://gamma-api.polymarket.com/markets"
            params = {
                "limit": 50,
                "closed": "false"
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            cutoff_time = datetime.now() - timedelta(hours=self.lookback_hours)
            new_markets = []

            # Handle both list response and dict with "data" key
            markets_list = data if isinstance(data, list) else data.get("data", [])
            for market in markets_list:
                market_id = market.get("id")
                created_at = market.get("createdAt")
                
                if market_id in self.seen_markets:
                    continue
                
                if created_at:
                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    if created_time > cutoff_time:
                        new_markets.append(market)
                        self.seen_markets.add(market_id)
            
            # Analyze new markets for early opportunity indicators
            for market in new_markets:
                opportunity = self.analyze_new_market(market)
                if opportunity:
                    opportunities.append(opportunity)
                    logger.info(f"Found new market opportunity: {opportunity.market}")
            
            # Save updated seen markets
            self.save_seen_markets()
            
        except Exception as e:
            logger.error(f"Error in new market scan: {e}")
        
        return opportunities
    
    def analyze_new_market(self, market: dict) -> Optional[AlphaOpportunity]:
        """Analyze a new market for early entry opportunity"""
        question = market.get("question", "")
        volume_24h = float(market.get("volume24hr", 0))
        
        # Low volume + interesting topic = potential early opportunity
        interesting_keywords = [
            "election", "crypto", "bitcoin", "ethereum", "weather", 
            "sports", "earnings", "fed", "rate", "ukraine", "china"
        ]
        
        is_interesting = any(keyword in question.lower() for keyword in interesting_keywords)
        is_low_volume = volume_24h < 1000  # Less than $1000 volume
        
        if is_interesting and is_low_volume:
            end_date = market.get("endDate", "")
            expires = datetime.fromisoformat(end_date.replace('Z', '+00:00')).isoformat() if end_date else ""
            
            return AlphaOpportunity(
                market=question,
                market_id=market.get("id", ""),
                edge="20%",  # Estimated early mover advantage
                direction="YES",  # Default, requires manual analysis
                confidence="low",
                expires=expires,
                source="new_market",
                market_url=f"https://polymarket.com/market/{market.get('slug', '')}",
                volume_24h=volume_24h,
                reasoning=f"New market with low volume (${volume_24h:.0f}), early entry opportunity"
            )
        
        return None

class AlphaScanner:
    """Main alpha scanner orchestrating all detection methods"""
    
    def __init__(self):
        self.weather_scanner = WeatherArbitrageScanner()
        self.whale_scanner = WhaleConsensusScanner()
        self.new_market_scanner = NewMarketScanner()
        self.output_file = "/output/polymarket_alpha.json"
        self.action_items_file = "/output/action_items.json"
    
    def scan_all(self) -> List[AlphaOpportunity]:
        """Run all scanners and return combined opportunities"""
        all_opportunities = []
        
        # Run individual scanners
        weather_opps = self.weather_scanner.scan()
        whale_opps = self.whale_scanner.scan()
        new_market_opps = self.new_market_scanner.scan()
        
        all_opportunities.extend(weather_opps)
        all_opportunities.extend(whale_opps)
        all_opportunities.extend(new_market_opps)
        
        return all_opportunities
    
    def save_opportunities(self, opportunities: List[AlphaOpportunity]):
        """Save opportunities to dashboard data file"""
        try:
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
            
            # Convert to dashboard format
            dashboard_data = {
                "opportunities": [asdict(opp) for opp in opportunities],
                "performance": {
                    "paperTrades": 0,
                    "wins": 0,
                    "losses": 0,
                    "theoreticalPnL": 0
                },
                "lastScan": datetime.now().isoformat()
            }
            
            with open(self.output_file, 'w') as f:
                json.dump(dashboard_data, f, indent=2)
            
            logger.info(f"Saved {len(opportunities)} opportunities to {self.output_file}")
            
        except Exception as e:
            logger.error(f"Error saving opportunities: {e}")
    
    def create_alerts(self, opportunities: List[AlphaOpportunity]):
        """Create urgent alerts for high-confidence opportunities"""
        try:
            urgent_opportunities = [
                opp for opp in opportunities 
                if opp.confidence == "high" and float(opp.edge.rstrip('%')) >= 30
            ]
            
            if not urgent_opportunities:
                return
            
            # Load existing action items
            action_items = []
            if os.path.exists(self.action_items_file):
                with open(self.action_items_file, 'r') as f:
                    action_items = json.load(f)
            
            # Add urgent opportunities as action items
            for opp in urgent_opportunities:
                action_item = {
                    "id": f"polymarket_{opp.market_id}",
                    "title": f"🚨 POLYMARKET ALPHA: {opp.edge} edge detected",
                    "description": f"{opp.market} - {opp.reasoning}",
                    "priority": "urgent",
                    "category": "trading",
                    "url": opp.market_url,
                    "created": datetime.now().isoformat(),
                    "due": opp.expires
                }
                
                # Check if already exists
                exists = any(item.get("id") == action_item["id"] for item in action_items)
                if not exists:
                    action_items.append(action_item)
            
            # Save updated action items
            os.makedirs(os.path.dirname(self.action_items_file), exist_ok=True)
            with open(self.action_items_file, 'w') as f:
                json.dump(action_items, f, indent=2)
            
            logger.info(f"Created {len(urgent_opportunities)} urgent alerts")
            
        except Exception as e:
            logger.error(f"Error creating alerts: {e}")
    
    def run_scan(self):
        """Main scan execution"""
        logger.info("=== Starting Polymarket Alpha Scan ===")
        
        try:
            opportunities = self.scan_all()
            
            logger.info(f"Found {len(opportunities)} total opportunities:")
            for opp in opportunities:
                logger.info(f"  - {opp.source}: {opp.market} ({opp.edge} edge, {opp.confidence})")
            
            self.save_opportunities(opportunities)
            self.create_alerts(opportunities)
            
            logger.info("=== Alpha scan complete ===")
            
        except Exception as e:
            logger.error(f"Error in main scan: {e}")

def run_scheduled_scans():
    """Set up scheduled scanning"""
    scanner = AlphaScanner()
    
    # Schedule different scan frequencies
    schedule.every(30).minutes.do(scanner.new_market_scanner.scan)  # New markets every 30 min
    schedule.every().hour.do(scanner.whale_scanner.scan)  # Whale consensus every hour
    schedule.every(2).hours.do(scanner.weather_scanner.scan)  # Weather every 2 hours
    schedule.every(30).minutes.do(scanner.run_scan)  # Full scan every 30 min
    
    logger.info("Scheduled alpha scanner started")
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "schedule":
        run_scheduled_scans()
    else:
        # Run single scan
        scanner = AlphaScanner()
        scanner.run_scan()