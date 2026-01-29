#!/usr/bin/env python3
"""
Weather Arbitrage Scanner for Polymarket Dashboard Integration
Integrated version of the arbitrage scanner optimized for dashboard data generation.
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import logging
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup
import re
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

@dataclass
class ArbitrageOpportunity:
    """Represents a potential arbitrage opportunity"""
    market_name: str
    market_url: str
    current_price: float
    true_probability: float
    edge: float
    expected_value: float
    confidence: float
    data_source: str
    volume: str
    expires: datetime
    signal_strength: str  # 'strong', 'medium', 'weak'
    category: str = "weather"

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'market_name': self.market_name,
            'market_url': self.market_url,
            'current_price': self.current_price,
            'true_probability': self.true_probability,
            'edge': self.edge,
            'expected_value': self.expected_value,
            'confidence': self.confidence,
            'data_source': self.data_source,
            'volume': self.volume,
            'expires': self.expires.isoformat() if isinstance(self.expires, datetime) else self.expires,
            'signal_strength': self.signal_strength,
            'category': self.category
        }

class WeatherDataProvider:
    """Fetches real-time weather data"""
    
    def __init__(self, openweather_api_key: Optional[str] = None):
        self.openweather_api_key = openweather_api_key
        self.session = requests.Session()
        # Cache results for 15 minutes to avoid API limits
        self._cache = {}
        self._cache_ttl = 900  # 15 minutes
        
    def get_current_temperature(self, city: str, country: str = "US") -> Optional[float]:
        """Get current temperature for a city with caching"""
        cache_key = f"{city}_{country}"
        now = datetime.now()
        
        # Check cache first
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if (now - cached_time).seconds < self._cache_ttl:
                return cached_data
        
        # For demo, use mock temperature data for major cities
        mock_temps = {
            'Miami': 76.0,      # Warm as expected
            'Chicago': 28.0,    # Cold winter
            'Los Angeles': 72.0,# Nice weather
            'Dallas': 58.0,     # Mild winter
            'Seattle': 48.0,    # Typical Pacific NW
            'New York': 35.0,   # Cold winter
            'Houston': 62.0,    # Mild Texas winter
            'Phoenix': 68.0,    # Warm desert winter
            'San Francisco': 55.0, # Cool California
            'Boston': 30.0      # Cold northeast
        }
        
        if city in mock_temps:
            temp = mock_temps[city]
            self._cache[cache_key] = (temp, now)
            return temp
        
        try:
            # Try free weather service first (no API key needed)
            temp = self._get_weather_fallback(city, country)
            
            if temp is None and self.openweather_api_key:
                # Fallback to OpenWeatherMap if available
                url = f"https://api.openweathermap.org/data/2.5/weather"
                params = {
                    'q': f"{city},{country}",
                    'appid': self.openweather_api_key,
                    'units': 'imperial' if country == 'US' else 'metric'
                }
                response = self.session.get(url, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    temp = data['main']['temp']
            
            # Cache successful results
            if temp is not None:
                self._cache[cache_key] = (temp, now)
            
            return temp
            
        except Exception as e:
            logger.error(f"Error fetching weather for {city}: {e}")
            return None
    
    def _get_weather_fallback(self, city: str, country: str) -> Optional[float]:
        """Fallback weather data from free sources"""
        try:
            # Use wttr.in service (free, no API key needed)
            url = f"https://wttr.in/{city}?format=j1"
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if country == "US":
                    temp_f = float(data['current_condition'][0]['temp_F'])
                    return temp_f
                else:
                    temp_c = float(data['current_condition'][0]['temp_C'])
                    return temp_c
                    
        except Exception as e:
            logger.debug(f"Fallback weather failed for {city}: {e}")
            
        return None

class PolymarketScraper:
    """Simplified scraper for weather markets"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def get_demo_weather_markets(self) -> List[Dict]:
        """Return demo weather markets for integration testing"""
        # In a real implementation, this would scrape actual markets
        # For now, return realistic demo data based on current weather patterns
        
        demo_markets = [
            {
                'title': "Temperature in Miami above 70°F on January 28?",
                'url': "https://polymarket.com/event/miami-temp-above-70f-jan-28",
                'betting_options': [
                    {'option': 'Yes', 'probability': 0.35},  # Market underpricing
                    {'option': 'No', 'probability': 0.65}
                ],
                'volume': "$77k Vol.",
                'scraped_at': datetime.now()
            },
            {
                'title': "Temperature in Chicago above 32°F tomorrow?",
                'url': "https://polymarket.com/event/chicago-temp-above-32f", 
                'betting_options': [
                    {'option': 'Yes', 'probability': 0.80},  # Market overpricing winter warmth
                    {'option': 'No', 'probability': 0.20}
                ],
                'volume': "$45k Vol.",
                'scraped_at': datetime.now()
            },
            {
                'title': "Temperature in Los Angeles above 65°F today?",
                'url': "https://polymarket.com/event/la-temp-above-65f",
                'betting_options': [
                    {'option': 'Yes', 'probability': 0.45},  # Market underpricing CA weather
                    {'option': 'No', 'probability': 0.55}
                ],
                'volume': "$82k Vol.",
                'scraped_at': datetime.now()
            },
            {
                'title': "Temperature in Dallas above 50°F tomorrow?",
                'url': "https://polymarket.com/event/dallas-temp-above-50f",
                'betting_options': [
                    {'option': 'Yes', 'probability': 0.25},  # Market severely underpricing
                    {'option': 'No', 'probability': 0.75}
                ],
                'volume': "$35k Vol.",
                'scraped_at': datetime.now()
            },
            {
                'title': "Temperature in Seattle above 45°F on January 29?",
                'url': "https://polymarket.com/event/seattle-temp-above-45f",
                'betting_options': [
                    {'option': 'Yes', 'probability': 0.60},  # Reasonable pricing
                    {'option': 'No', 'probability': 0.40}
                ],
                'volume': "$28k Vol.",
                'scraped_at': datetime.now()
            }
        ]
        
        return demo_markets

class ArbitrageAnalyzer:
    """Analyzes markets for arbitrage opportunities"""
    
    def __init__(self, weather_provider: WeatherDataProvider):
        self.weather = weather_provider
        
    def analyze_temperature_market(self, market: Dict) -> Optional[ArbitrageOpportunity]:
        """Analyze a temperature prediction market for arbitrage"""
        
        city_temp = self._extract_city_and_temp(market['title'])
        if not city_temp:
            return None
            
        city, target_temp_f, is_over = city_temp
        
        # Get current weather data
        current_temp = self.weather.get_current_temperature(city)
        if current_temp is None:
            logger.warning(f"Could not get weather data for {city}")
            return None
            
        # Calculate probability based on current temperature
        true_probability = self._calculate_temperature_probability(
            current_temp, target_temp_f, is_over
        )
        
        if true_probability is None:
            return None
            
        # Find best betting option
        best_market_prob = None
        best_option = None
        
        for option in market['betting_options']:
            if (is_over and option['option'] == 'Yes') or (not is_over and option['option'] == 'No'):
                market_prob = option['probability']
                if best_market_prob is None:
                    best_market_prob = market_prob
                    best_option = option['option']
        
        if best_market_prob is None:
            return None
            
        # Calculate edge and expected value
        edge = abs(true_probability - best_market_prob)
        
        # Only consider opportunities with meaningful edge
        if edge < 0.05:  # 5% minimum edge for dashboard (lowered for demo)
            return None
            
        # Calculate expected value
        if true_probability > best_market_prob:
            expected_value = (true_probability - best_market_prob) / best_market_prob
            should_bet = "YES" if is_over else "NO"
        else:
            expected_value = (best_market_prob - true_probability) / (1 - best_market_prob)
            should_bet = "NO" if is_over else "YES"
        
        # Determine signal strength
        if edge >= 0.40:
            signal_strength = "strong"
        elif edge >= 0.25:
            signal_strength = "medium"
        else:
            signal_strength = "weak"
        
        return ArbitrageOpportunity(
            market_name=market['title'],
            market_url=market['url'],
            current_price=best_market_prob,
            true_probability=true_probability,
            edge=edge,
            expected_value=expected_value,
            confidence=0.8,
            data_source=f"Current temp: {current_temp:.1f}°F",
            volume=market['volume'],
            expires=datetime.now() + timedelta(hours=24),
            signal_strength=signal_strength
        )
    
    def _extract_city_and_temp(self, title: str) -> Optional[Tuple[str, float, bool]]:
        """Extract city name and temperature target from market title"""
        try:
            city_patterns = {
                'NYC': 'New York', 'New York': 'New York',
                'London': 'London',
                'Seoul': 'Seoul',
                'Dallas': 'Dallas', 
                'Miami': 'Miami',
                'Toronto': 'Toronto',
                'Seattle': 'Seattle',
                'Ankara': 'Ankara',
                'LA': 'Los Angeles', 'Los Angeles': 'Los Angeles',
                'Chicago': 'Chicago',
                'Houston': 'Houston'
            }
            
            title_lower = title.lower()
            city = None
            
            for pattern, full_name in city_patterns.items():
                if pattern.lower() in title_lower:
                    city = full_name
                    break
                    
            if not city:
                return None
            
            # Extract temperature target
            temp_match = re.search(r'(\d+)°?([CF])', title)
            if not temp_match:
                # Try other patterns like "45°F" or "above 64"
                temp_match = re.search(r'above (\d+)|(\d+)°', title)
                if temp_match:
                    temp_value = float(temp_match.group(1) or temp_match.group(2))
                    temp_unit = 'F'  # Assume Fahrenheit for US cities
                else:
                    return None
            else:
                temp_value = float(temp_match.group(1))
                temp_unit = temp_match.group(2).upper()
            
            # Convert to Fahrenheit if needed
            if temp_unit == 'C':
                temp_f = temp_value * 9/5 + 32
            else:
                temp_f = temp_value
            
            # Determine if it's "over" or "under"
            is_over = any(word in title_lower for word in ['above', 'over', 'higher', 'highest'])
            
            return city, temp_f, is_over
            
        except Exception as e:
            logger.error(f"Error extracting city/temp from '{title}': {e}")
            return None
    
    def _calculate_temperature_probability(self, current_temp: float, 
                                         target_temp: float, is_over: bool) -> Optional[float]:
        """Calculate probability based on current conditions"""
        
        temp_diff = current_temp - target_temp
        
        # Simple model based on current temperature proximity
        if is_over:
            # Question: "Will temp be above target?"
            if current_temp > target_temp:
                # Already above target - very likely to stay above
                if temp_diff >= 5:
                    return 0.90
                elif temp_diff >= 2:
                    return 0.80
                else:
                    return 0.70
            else:
                # Below target - less likely to reach
                if temp_diff <= -10:
                    return 0.10
                elif temp_diff <= -5:
                    return 0.25
                else:
                    return 0.40
        else:
            # Question: "Will temp be below target?"
            if current_temp < target_temp:
                # Already below target
                if abs(temp_diff) >= 5:
                    return 0.90
                elif abs(temp_diff) >= 2:
                    return 0.80
                else:
                    return 0.70
            else:
                # Above target - less likely to go below
                if temp_diff >= 10:
                    return 0.10
                elif temp_diff >= 5:
                    return 0.25
                else:
                    return 0.40

class WeatherArbitrageScanner:
    """Main scanner for dashboard integration"""
    
    def __init__(self, openweather_api_key: Optional[str] = None):
        self.weather = WeatherDataProvider(openweather_api_key)
        self.scraper = PolymarketScraper()
        self.analyzer = ArbitrageAnalyzer(self.weather)
        
    def scan_for_opportunities(self, use_demo: bool = True) -> List[ArbitrageOpportunity]:
        """Scan for arbitrage opportunities"""
        logger.info("Scanning for weather arbitrage opportunities...")
        
        opportunities = []
        
        try:
            # Get weather markets (demo for now)
            if use_demo:
                markets = self.scraper.get_demo_weather_markets()
            else:
                # In production, would scrape actual markets
                markets = []
            
            logger.info(f"Analyzing {len(markets)} weather markets")
            
            # Analyze each market
            for market in markets:
                try:
                    opportunity = self.analyzer.analyze_temperature_market(market)
                    if opportunity:
                        opportunities.append(opportunity)
                        logger.info(f"Found opportunity: {opportunity.market_name} - Edge: {opportunity.edge:.2%}")
                        
                except Exception as e:
                    logger.error(f"Error analyzing market {market.get('title', 'Unknown')}: {e}")
                    
                # Rate limiting
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error in weather arbitrage scan: {e}")
            
        logger.info(f"Weather arbitrage scan complete. Found {len(opportunities)} opportunities.")
        return opportunities
    
    def get_dashboard_data(self) -> Dict:
        """Get weather arbitrage data formatted for dashboard"""
        opportunities = self.scan_for_opportunities()
        
        # Sort by signal strength and edge
        opportunities.sort(key=lambda x: (
            {'strong': 3, 'medium': 2, 'weak': 1}.get(x.signal_strength, 0),
            x.edge
        ), reverse=True)
        
        # Categorize by signal strength
        strong_signals = [opp for opp in opportunities if opp.signal_strength == 'strong']
        medium_signals = [opp for opp in opportunities if opp.signal_strength == 'medium']
        weak_signals = [opp for opp in opportunities if opp.signal_strength == 'weak']
        
        return {
            'opportunities': [opp.to_dict() for opp in opportunities],
            'summary': {
                'total_opportunities': len(opportunities),
                'strong_signals': len(strong_signals),
                'medium_signals': len(medium_signals), 
                'weak_signals': len(weak_signals),
                'avg_edge': sum(opp.edge for opp in opportunities) / len(opportunities) if opportunities else 0,
                'best_opportunity': opportunities[0].to_dict() if opportunities else None
            },
            'generated_at': datetime.now().isoformat()
        }

# Integration function for dashboard
def get_weather_arbitrage_data() -> Dict:
    """Main function to get weather arbitrage data for dashboard"""
    try:
        scanner = WeatherArbitrageScanner()
        return scanner.get_dashboard_data()
    except Exception as e:
        logger.error(f"Error generating weather arbitrage data: {e}")
        return {
            'opportunities': [],
            'summary': {
                'total_opportunities': 0,
                'strong_signals': 0,
                'medium_signals': 0,
                'weak_signals': 0,
                'avg_edge': 0,
                'best_opportunity': None,
                'error': str(e)
            },
            'generated_at': datetime.now().isoformat()
        }

if __name__ == "__main__":
    # Test the scanner
    scanner = WeatherArbitrageScanner()
    data = scanner.get_dashboard_data()
    print(json.dumps(data, indent=2))