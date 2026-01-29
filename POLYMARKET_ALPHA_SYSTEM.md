# 🎯 Polymarket Alpha System

A comprehensive edge detection and paper trading system for exploiting information asymmetries on Polymarket prediction markets.

## 🎯 System Overview

This system continuously scans for profitable opportunities across multiple dimensions:

- **Weather Arbitrage**: Compare real weather forecasts vs market prices
- **Whale Consensus**: Detect when skilled traders agree on market direction  
- **New Market Sniping**: Early entry opportunities on newly launched markets
- **Paper Trading**: Track theoretical performance before deploying real capital

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Alpha Scanner │ ──>│ Mission Control │ ──>│ Action Items    │
│   (Every 30min) │    │    Dashboard    │    │ (Urgent Alerts)│
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │
         v                       │
┌─────────────────┐              │
│ Paper Trading   │ <────────────┘
│    Tracker      │
└─────────────────┘
```

## 📊 Components

### 1. Alpha Scanner (`alpha_scanner.py`)

**Purpose**: Main edge detection engine

**Scanners**:
- **Weather Scanner** (every 2 hours): Compares Open-Meteo forecasts vs Polymarket weather prices
- **Whale Consensus** (every hour): Finds markets where 3+ skilled whales agree  
- **New Market Sniping** (every 30 min): Flags newly launched markets for early entry

**Output**: `polymarket_alpha.json` with detected opportunities

**Thresholds**:
- Weather: >15% edge required
- Whale: 3+ whales with >65% win rate
- Alerts: >30% edge + high confidence

### 2. Paper Trading Tracker (`paper_trading_tracker.py`)

**Purpose**: Tracks theoretical performance without real money

**Functions**:
- Records all detected opportunities as $100 paper trades
- Monitors market resolution and calculates P&L
- Builds track record over time
- Updates dashboard with performance metrics

**Output**: `paper_trades.json` with trade history and metrics

### 3. Dashboard Integration

**Location**: Mission Control (`D:\docker\daily-briefing\`)

**New Section**: 📈 POLYMARKET ALPHA displays:
- Current opportunities with confidence levels
- Performance stats (win rate, theoretical P&L)
- Source breakdown (weather, whale, new market)

### 4. Alert System

**Triggers**: High-confidence opportunities (>30% edge + whale consensus)

**Output**: Urgent action items in Mission Control dashboard

## 🚀 Quick Start

### Prerequisites
```bash
# Required APIs (all free):
# - Open-Meteo (weather): No API key needed
# - Polymarket Gamma API: Public endpoints
# - Existing whale tracker database
```

### Deploy
```bash
# Start the system
cd D:\docker\polymarket-dashboard\
docker-compose up -d alpha-scanner paper-trader

# View logs
docker-compose logs -f alpha-scanner
docker-compose logs -f paper-trader

# Check dashboard
# Visit your Mission Control dashboard to see new Polymarket Alpha section
```

## 📈 Key Data Sources

### Weather Data
- **API**: Open-Meteo (https://api.open-meteo.com/v1/forecast)
- **Cities**: NYC, London, Tokyo, LA
- **Cost**: Free, no API key required
- **Update**: Every 2 hours

### Polymarket Data  
- **Gamma API**: https://gamma-api.polymarket.com/markets
- **Data API**: https://data-api.polymarket.com
- **Cost**: Free public endpoints
- **Rate Limit**: Reasonable for our usage

### Whale Database
- **Source**: Existing tracker at `/data/whales.db`
- **Filter**: >65% win rate, 10+ trades minimum
- **Update**: Real-time from existing tracker

## 🎪 Example Opportunities

### Weather Arbitrage
```json
{
  "market": "Will NYC reach 75°F on January 30?",
  "edge": "42%",
  "direction": "YES",
  "confidence": "high",
  "source": "weather",
  "reasoning": "Forecast shows 85% chance vs market 43%"
}
```

### Whale Consensus
```json
{
  "market": "Will Bitcoin hit $100k by March?", 
  "edge": "25%",
  "direction": "NO",
  "confidence": "high", 
  "source": "whale",
  "reasoning": "5 skilled whales agree on NO"
}
```

### New Market
```json
{
  "market": "Will Apple announce VR headset at WWDC?",
  "edge": "20%", 
  "direction": "YES",
  "confidence": "low",
  "source": "new_market",
  "reasoning": "New market with low volume ($500), early entry opportunity"
}
```

## 📊 Performance Tracking

### Paper Trading Metrics
- **Trade Size**: $100 per opportunity
- **Win Rate**: Percentage of profitable trades
- **Total P&L**: Cumulative theoretical profit/loss
- **Sharpe Ratio**: Risk-adjusted returns
- **Max Drawdown**: Largest peak-to-trough loss

### Success Criteria
- **2-week track record** of consistent paper profits
- **>60% win rate** on high-confidence trades
- **Positive expected value** across all sources
- **Low drawdown** (<20% of capital)

## 🚨 Risk Management

### Position Sizing
- Start with $100 paper trades
- Scale gradually based on confidence
- Never risk more than 5% on single trade

### Confidence Levels
- **High**: Weather + forecast certainty OR 5+ whale consensus
- **Medium**: 3-4 whale consensus OR strong weather edge  
- **Low**: New markets, single indicators

### Stop Conditions
- Paper losses exceed $1000
- Win rate drops below 45%
- System shows consistent bias

## 🔧 Configuration

### Scanner Settings (`alpha_scanner.py`)
```python
# Weather edge threshold
MIN_WEATHER_EDGE = 0.15  # 15%

# Whale consensus minimum
MIN_WHALE_COUNT = 3
MIN_WHALE_WIN_RATE = 0.65  # 65%

# Alert threshold
ALERT_EDGE_THRESHOLD = 0.30  # 30%

# Cities to monitor
WEATHER_CITIES = ["NYC", "London", "Tokyo", "LA"]
```

### Paper Trading (`paper_trading_tracker.py`)
```python
# Trade parameters
BET_SIZE = 100  # $100 per trade
UPDATE_FREQUENCY = 1800  # 30 minutes

# Performance calculation
WIN_RATE_THRESHOLD = 0.60
MAX_DRAWDOWN_THRESHOLD = 0.20
```

## 📁 File Structure

```
D:\docker\polymarket-dashboard\
├── alpha_scanner.py              # Main edge detection
├── paper_trading_tracker.py      # Performance tracking
├── docker-compose.yml            # Updated with new services
├── POLYMARKET_ALPHA_SYSTEM.md    # This documentation
└── data/
    ├── whales.db                 # Existing whale data
    ├── seen_markets.json         # New market tracking
    └── seen_opportunities.json   # Paper trade tracking

D:\docker\daily-briefing\
├── generate.js                   # Updated dashboard generator  
├── templates/index.html          # Updated with Polymarket section
└── data/
    ├── polymarket_alpha.json     # Current opportunities
    ├── paper_trades.json         # Paper trading history
    └── action_items.json         # Alert integration
```

## 🎯 Next Steps

### Phase 1: Paper Trading (Weeks 1-2)
- [ ] Deploy alpha scanner system
- [ ] Monitor paper trading performance
- [ ] Refine edge detection algorithms
- [ ] Build 2-week track record

### Phase 2: Live Trading (Week 3+)
- [ ] If paper profits consistent, deploy real capital
- [ ] Start with $50-100 real trades
- [ ] Scale position sizes based on confidence
- [ ] Implement automated execution

### Phase 3: Optimization (Month 2+)
- [ ] Machine learning for edge detection
- [ ] Sentiment analysis integration  
- [ ] Cross-market arbitrage
- [ ] Portfolio optimization

## 🚀 Expected Outcomes

Based on initial research:

### Conservative Estimates
- **Weather Arbitrage**: 15-30% edges, 1-2 opportunities/day
- **Whale Consensus**: 20-25% edges, 2-3 opportunities/week  
- **New Markets**: 10-20% edges, 3-5 opportunities/week

### Projected Performance (2-week paper trading)
- **Total Opportunities**: 50-70 paper trades
- **Expected Win Rate**: 60-70%
- **Theoretical P&L**: $500-1500
- **Sharpe Ratio**: 1.5-2.5

### Success Metrics
- **Break-even**: 50% win rate (due to edge sizes)
- **Good**: 60%+ win rate, positive Sharpe
- **Excellent**: 70%+ win rate, Sharpe >2

## ⚠️ Important Notes

### Legal & Compliance
- Polymarket operates under Bermuda regulations
- US users may face restrictions
- Always verify local laws before trading

### Risk Warnings  
- Past performance doesn't guarantee future results
- Market conditions can change rapidly
- Start small and scale gradually
- Never risk more than you can afford to lose

### Data Dependency
- Weather APIs can have outages
- Polymarket APIs may change
- Whale tracking depends on transaction data availability

## 📞 Support

For issues or questions:
1. Check docker-compose logs first
2. Verify API endpoints are accessible  
3. Ensure data directories exist and are writable
4. Review confidence thresholds if no opportunities detected

---

**🎯 Goal**: Build systematic edge detection that consistently finds profitable opportunities across multiple information sources, validated through rigorous paper trading before deploying real capital.