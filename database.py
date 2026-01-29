"""SQLite database helpers for whale tracking."""

import sqlite3
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "whales.db"):
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._init_tables()

    def _connect(self):
        """Establish database connection."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        logger.info(f"Connected to database: {self.db_path}")

    def _init_tables(self):
        """Create tables if they don't exist."""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS whales (
                address TEXT PRIMARY KEY,
                first_seen TIMESTAMP,
                total_volume REAL,
                win_count INTEGER DEFAULT 0,
                loss_count INTEGER DEFAULT 0,
                notes TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                whale_address TEXT,
                market_id TEXT,
                market_question TEXT,
                side TEXT,
                size REAL,
                entry_price REAL,
                entry_time TIMESTAMP,
                resolved BOOLEAN DEFAULT FALSE,
                outcome TEXT,
                pnl REAL,
                FOREIGN KEY (whale_address) REFERENCES whales(address)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                market_id TEXT PRIMARY KEY,
                question TEXT,
                resolved BOOLEAN DEFAULT FALSE,
                resolution TEXT,
                resolved_at TIMESTAMP
            )
        """)

        # Track seen markets for new market detection + profit tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seen_markets (
                condition_id TEXT PRIMARY KEY,
                slug TEXT,
                question TEXT,
                first_seen TIMESTAMP,
                volume REAL DEFAULT 0,
                liquidity REAL DEFAULT 0,
                initial_yes_price REAL,
                initial_no_price REAL,
                price_1hr_yes REAL,
                price_24hr_yes REAL,
                price_7d_yes REAL,
                checked_1hr BOOLEAN DEFAULT FALSE,
                checked_24hr BOOLEAN DEFAULT FALSE,
                checked_7d BOOLEAN DEFAULT FALSE
            )
        """)

        # Create indexes for faster lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_whale ON trades(whale_address)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_resolved ON trades(resolved)")

        self.conn.commit()
        logger.info("Database tables initialized")

    # Whale operations
    def add_whale(self, address: str, total_volume: float, notes: str = None) -> bool:
        """Add a new whale to tracking."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO whales (address, first_seen, total_volume, notes)
                VALUES (?, ?, ?, ?)
            """, (address, datetime.utcnow(), total_volume, notes))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error adding whale {address}: {e}")
            return False

    def get_whale(self, address: str) -> Optional[dict]:
        """Get whale by address."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM whales WHERE address = ?", (address,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_whales(self) -> list:
        """Get all tracked whales."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM whales")
        return [dict(row) for row in cursor.fetchall()]

    def update_whale_volume(self, address: str, total_volume: float):
        """Update whale's total volume."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE whales SET total_volume = ? WHERE address = ?
        """, (total_volume, address))
        self.conn.commit()

    def update_whale_stats(self, address: str, win_count: int, loss_count: int):
        """Update whale win/loss counts."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE whales SET win_count = ?, loss_count = ? WHERE address = ?
        """, (win_count, loss_count, address))
        self.conn.commit()

    def get_whale_win_rate(self, address: str) -> tuple:
        """Get whale's win rate. Returns (win_count, loss_count, win_rate)."""
        whale = self.get_whale(address)
        if not whale:
            return (0, 0, 0.0)

        wins = whale['win_count'] or 0
        losses = whale['loss_count'] or 0
        total = wins + losses
        rate = (wins / total * 100) if total > 0 else 0.0
        return (wins, losses, rate)

    # Trade operations
    def add_trade(self, whale_address: str, market_id: str, market_question: str,
                  side: str, size: float, entry_price: float) -> int:
        """Add a new trade. Returns trade ID."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO trades (whale_address, market_id, market_question, side, size, entry_price, entry_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (whale_address, market_id, market_question, side, size, entry_price, datetime.utcnow()))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding trade: {e}")
            return -1

    def get_trade(self, trade_id: int) -> Optional[dict]:
        """Get trade by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_unresolved_trades(self) -> list:
        """Get all trades that haven't been resolved yet."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE resolved = FALSE")
        return [dict(row) for row in cursor.fetchall()]

    def get_whale_trades(self, whale_address: str) -> list:
        """Get all trades for a specific whale."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE whale_address = ? ORDER BY entry_time DESC", (whale_address,))
        return [dict(row) for row in cursor.fetchall()]

    def trade_exists(self, whale_address: str, market_id: str, side: str) -> bool:
        """Check if a trade already exists (to avoid duplicates)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 1 FROM trades
            WHERE whale_address = ? AND market_id = ? AND side = ?
        """, (whale_address, market_id, side))
        return cursor.fetchone() is not None

    def resolve_trade(self, trade_id: int, outcome: str, pnl: float):
        """Mark a trade as resolved with outcome and PnL."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE trades SET resolved = TRUE, outcome = ?, pnl = ?
            WHERE id = ?
        """, (outcome, pnl, trade_id))
        self.conn.commit()

    def resolve_trades_by_market(self, market_id: str, resolution: str):
        """Resolve all trades for a market based on its resolution."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM trades WHERE market_id = ? AND resolved = FALSE
        """, (market_id,))
        trades = [dict(row) for row in cursor.fetchall()]

        for trade in trades:
            # Determine if trade won based on side and market resolution
            side = trade['side'].upper()
            won = (side == "YES" and resolution == "YES") or (side == "NO" and resolution == "NO")
            outcome = "WIN" if won else "LOSS"

            # Calculate PnL
            size = trade['size']
            entry_price = trade['entry_price']
            if won:
                # Won: profit = size * (1 - entry_price)
                pnl = size * (1 - entry_price)
            else:
                # Lost: loss = size * entry_price (what was paid)
                pnl = -size * entry_price

            self.resolve_trade(trade['id'], outcome, pnl)

            # Update whale stats
            whale = self.get_whale(trade['whale_address'])
            if whale:
                if outcome == "WIN":
                    self.update_whale_stats(trade['whale_address'],
                                          whale['win_count'] + 1, whale['loss_count'])
                else:
                    self.update_whale_stats(trade['whale_address'],
                                          whale['win_count'], whale['loss_count'] + 1)

        return len(trades)

    # Market operations
    def add_market(self, market_id: str, question: str) -> bool:
        """Add a new market."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO markets (market_id, question)
                VALUES (?, ?)
            """, (market_id, question))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error adding market {market_id}: {e}")
            return False

    def get_market(self, market_id: str) -> Optional[dict]:
        """Get market by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM markets WHERE market_id = ?", (market_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_unresolved_markets(self) -> list:
        """Get all unresolved markets we're tracking."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT m.* FROM markets m
            INNER JOIN trades t ON m.market_id = t.market_id
            WHERE m.resolved = FALSE AND t.resolved = FALSE
        """)
        return [dict(row) for row in cursor.fetchall()]

    def resolve_market(self, market_id: str, resolution: str):
        """Mark a market as resolved."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE markets SET resolved = TRUE, resolution = ?, resolved_at = ?
            WHERE market_id = ?
        """, (resolution, datetime.utcnow(), market_id))
        self.conn.commit()

        # Resolve all trades for this market
        resolved_count = self.resolve_trades_by_market(market_id, resolution)
        logger.info(f"Market {market_id} resolved as {resolution}, {resolved_count} trades updated")

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    # New market detection
    def is_market_seen(self, condition_id: str) -> bool:
        """Check if we've seen this market before."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM seen_markets WHERE condition_id = ?", (condition_id,))
        return cursor.fetchone() is not None

    def add_seen_market(self, condition_id: str, slug: str, question: str, 
                        volume: float = 0, liquidity: float = 0,
                        yes_price: float = None, no_price: float = None) -> bool:
        """Add a market to seen list with initial prices."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO seen_markets 
                (condition_id, slug, question, first_seen, volume, liquidity,
                 initial_yes_price, initial_no_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (condition_id, slug, question, datetime.utcnow(), volume, liquidity,
                  yes_price, no_price))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error adding seen market: {e}")
            return False

    def update_market_price(self, condition_id: str, timeframe: str, yes_price: float):
        """Update price checkpoint (1hr, 24hr, 7d)."""
        try:
            cursor = self.conn.cursor()
            if timeframe == "1hr":
                cursor.execute("""
                    UPDATE seen_markets SET price_1hr_yes = ?, checked_1hr = TRUE
                    WHERE condition_id = ?
                """, (yes_price, condition_id))
            elif timeframe == "24hr":
                cursor.execute("""
                    UPDATE seen_markets SET price_24hr_yes = ?, checked_24hr = TRUE
                    WHERE condition_id = ?
                """, (yes_price, condition_id))
            elif timeframe == "7d":
                cursor.execute("""
                    UPDATE seen_markets SET price_7d_yes = ?, checked_7d = TRUE
                    WHERE condition_id = ?
                """, (yes_price, condition_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating market price: {e}")

    def get_markets_needing_check(self, timeframe: str) -> list:
        """Get markets that need price check for given timeframe."""
        cursor = self.conn.cursor()
        now = datetime.utcnow()
        
        if timeframe == "1hr":
            cursor.execute("""
                SELECT * FROM seen_markets 
                WHERE checked_1hr = FALSE 
                AND first_seen < datetime(?, '-1 hour')
                AND initial_yes_price IS NOT NULL
            """, (now,))
        elif timeframe == "24hr":
            cursor.execute("""
                SELECT * FROM seen_markets 
                WHERE checked_24hr = FALSE 
                AND first_seen < datetime(?, '-24 hours')
                AND initial_yes_price IS NOT NULL
            """, (now,))
        elif timeframe == "7d":
            cursor.execute("""
                SELECT * FROM seen_markets 
                WHERE checked_7d = FALSE 
                AND first_seen < datetime(?, '-7 days')
                AND initial_yes_price IS NOT NULL
            """, (now,))
        
        return [dict(row) for row in cursor.fetchall()]

    def get_new_market_stats(self) -> dict:
        """Get profit statistics for new market entries."""
        cursor = self.conn.cursor()
        
        # Calculate average price movement
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                AVG(CASE WHEN price_1hr_yes > initial_yes_price 
                    THEN (price_1hr_yes - initial_yes_price) / initial_yes_price * 100 
                    ELSE NULL END) as avg_gain_1hr,
                AVG(CASE WHEN price_24hr_yes > initial_yes_price 
                    THEN (price_24hr_yes - initial_yes_price) / initial_yes_price * 100 
                    ELSE NULL END) as avg_gain_24hr,
                SUM(CASE WHEN price_24hr_yes > initial_yes_price THEN 1 ELSE 0 END) as winners_24hr,
                SUM(CASE WHEN checked_24hr = TRUE THEN 1 ELSE 0 END) as checked_24hr_count
            FROM seen_markets 
            WHERE initial_yes_price IS NOT NULL AND initial_yes_price > 0
        """)
        
        row = cursor.fetchone()
        return dict(row) if row else {}

    def get_seen_market_count(self) -> int:
        """Get count of seen markets."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM seen_markets")
        return cursor.fetchone()[0]
