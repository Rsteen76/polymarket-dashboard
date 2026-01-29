#!/usr/bin/env python3
import sqlite3

def check_database():
    conn = sqlite3.connect('data/whales.db')
    c = conn.cursor()
    
    # Get table schemas
    c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    
    print("=== DATABASE SCHEMA ===")
    for name, sql in tables:
        print(f"\nTable: {name}")
        print(sql)
    
    # Check current resolution stats
    print("\n=== RESOLUTION STATS ===")
    try:
        c.execute("SELECT COUNT(*) as total, SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved FROM trades")
        total, resolved = c.fetchone()
        print(f"Total trades: {total}")
        print(f"Resolved trades: {resolved}")
        print(f"Unresolved trades: {total - resolved}")
        
        if resolved > 0:
            c.execute("SELECT COUNT(*) as wins FROM trades WHERE outcome = 'WIN'")
            wins = c.fetchone()[0]
            c.execute("SELECT COUNT(*) as losses FROM trades WHERE outcome = 'LOSS'") 
            losses = c.fetchone()[0]
            print(f"Wins: {wins}")
            print(f"Losses: {losses}")
            print(f"Win rate: {wins/(wins+losses)*100:.1f}%")
            
            c.execute("SELECT SUM(pnl) as total_pnl FROM trades WHERE resolved = 1")
            total_pnl = c.fetchone()[0] or 0
            print(f"Total P&L: ${total_pnl:.2f}")
    except Exception as e:
        print(f"Error getting stats: {e}")
    
    # Check whale counts
    print("\n=== WHALE STATS ===")
    try:
        c.execute("SELECT COUNT(*) FROM whales")
        whale_count = c.fetchone()[0]
        print(f"Total whales: {whale_count}")
        
        c.execute("SELECT COUNT(*) FROM whales WHERE win_count > 0 OR loss_count > 0")
        active_whales = c.fetchone()[0]
        print(f"Whales with resolved trades: {active_whales}")
    except Exception as e:
        print(f"Error getting whale stats: {e}")
    
    conn.close()

if __name__ == "__main__":
    check_database()