# Polymarket Whale Tracker - Money-Making Redesign

## Goal
Turn raw whale data into actionable trading signals that generate consistent profit.

## The Strategy (Based on Research)
1. **Multi-whale confirmation** - Only trade when 2-3+ skilled whales agree
2. **Category-specific skill** - Track whale performance by market type
3. **Entry price matters** - Skip if slippage >10%
4. **Fade the losers** - Optionally counter-trade consistent losers

## Dashboard Views

### View 1: Smart Money Leaderboard
**Purpose:** Find whales worth following

Columns:
- Wallet (truncated)
- Skill Score (composite)
- Win Rate
- Total P&L
- Resolved Trades
- Best Category
- Open Positions

Filters:
- Min resolved trades (default: 5)
- Min win rate (default: 55%)
- Min P&L (default: $0)

Color coding:
- Green: Win rate >60%, P&L positive
- Yellow: Win rate 50-60%
- Red: Win rate <50% (fade candidates)

### View 2: Hot Markets (Consensus View)
**Purpose:** Find markets where smart money agrees - THE SIGNAL

Shows markets where multiple qualified whales have positions:
- Market name
- Whale consensus (e.g., "3 YES / 1 NO")
- Average entry price
- Current price
- Slippage %
- Which whales (click to expand)

Highlight when:
- 3+ skilled whales agree on same side = 🔥 STRONG SIGNAL
- Smart money vs retail divergence = 📊 CONTRARIAN OPPORTUNITY

### View 3: Recent Moves Feed
**Purpose:** Real-time awareness of whale activity

Chronological feed:
- Time
- Whale (with skill indicator)
- Market
- Side (YES/NO)
- Size
- Entry price
- Current price (slippage %)

Filter:
- Show only from skilled whales (score > X)
- Show only large positions (>$10K)

### View 4: Fade the Losers
**Purpose:** Counter-trade bad traders

Shows whales with:
- Negative P&L
- Win rate <45%
- Their current positions (to fade)

---

## Data Requirements

### Current data we have:
- whales: address, volume, wins, losses, P&L, open_trades, win_rate
- trades: whale_address, market_question, side, size, entry_price, entry_time
- resolved_trades: full trade history with outcomes
- whale_history: per-whale resolved trades

### Data we need to add:
1. **Current market prices** - to calculate slippage
2. **Market categories** - politics, sports, crypto, etc.
3. **Market resolution dates** - time-sensitive info
4. **Whale skill by category** - not just overall

### Calculated fields to add:
1. **Skill Score** = f(win_rate, P&L, trade_count, consistency)
2. **Category performance** - win rate per category
3. **Market consensus** - aggregate whale positions per market
4. **Slippage %** = (current_price - entry_price) / entry_price

---

## Alerts (Phase 2)

Telegram alerts for:
1. **Multi-whale signal**: "🐋 3+ skilled whales just bought YES on [Market]"
2. **New skilled whale move**: "[WhaleName] (72% WR) just entered [Market] at $0.45"
3. **Contrarian setup**: "Smart money buying NO while 80% retail is YES on [Market]"

---

## Automation (Phase 3)

Rules engine:
- IF 3+ skilled whales agree on market
- AND slippage <10%
- AND no offsetting positions (not farming)
- AND market category matches whale's specialty
- THEN alert or auto-execute

Position sizing:
- (whale_position / estimated_whale_bankroll) * your_bankroll
- Cap at X% of bankroll per trade
- Cap at Y% total exposure

---

## Technical Implementation

### dashboard.html changes:
1. Tabs: Leaderboard | Hot Markets | Recent Moves | Fade Losers
2. Real-time data refresh (30 sec for active trading)
3. Skill score calculation in JS
4. Market consensus aggregation
5. Slippage calculation

### Data pipeline changes (generate_dashboard.py):
1. Fetch current market prices from Polymarket API
2. Categorize markets (regex or API tags)
3. Calculate skill scores
4. Pre-compute market consensus

### New alerts (tracker.py):
1. Check for multi-whale consensus
2. Send Telegram when threshold hit

---

## Success Metrics

Track over time:
- Trades taken following signals
- Win rate of signal-based trades
- P&L from following the system
- False positive rate (signals that lost)

---

## Priority Order

1. **Today**: Smart Money Leaderboard + Hot Markets view
2. **This week**: Recent Moves feed + slippage calculation
3. **Next week**: Telegram alerts for multi-whale signals
4. **Future**: Automation + position sizing + tracking
