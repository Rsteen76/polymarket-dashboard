import sqlite3
conn = sqlite3.connect("/app/data/whales.db")
c = conn.cursor()
c.execute("PRAGMA table_info(trades)")
print("TRADES TABLE SCHEMA:")
for col in c.fetchall():
    print(f"  {col[1]} ({col[2]})")
print()
c.execute("SELECT whale_address, COUNT(*) as cnt FROM trades GROUP BY whale_address ORDER BY cnt DESC LIMIT 10")
print("TOP WHALES BY TRADE COUNT:")
for r in c.fetchall():
    print(f"  {r[0][:12]}... | {r[1]} trades")
print()
c.execute("SELECT COUNT(*) FROM trades WHERE resolved = 1")
print(f"RESOLVED TRADES: {c.fetchone()[0]}")
