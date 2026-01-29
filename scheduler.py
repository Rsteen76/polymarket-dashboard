#!/usr/bin/env python3
"""
Polymarket Dashboard Scheduler
Runs periodic updates for all data feeds
"""

import schedule
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def run_quick_update():
    logger.info("Running quick update (5 min cycle)...")
    result = subprocess.run(["python", "money_maker_scheduler.py", "--quick"], capture_output=True, text=True)
    logger.info(f"Quick update completed: {result.returncode}")

def run_signal_generation():
    logger.info("Running signal generation (15 min cycle)...")
    result = subprocess.run(["python", "money_maker_scheduler.py", "--signals-only"], capture_output=True, text=True)
    logger.info(f"Signal generation completed: {result.returncode}")

def run_weather_scan():
    logger.info("Running weather arbitrage scan (1 hour cycle)...")
    result = subprocess.run(["python", "weather_arbitrage.py"], capture_output=True, text=True)
    with open("/app/public/weather_data.json", "w") as f:
        f.write(result.stdout if result.stdout else "{}")
    logger.info(f"Weather scan completed: {result.returncode}")

def run_full_update():
    logger.info("Running full system update (6 hour cycle)...")
    result = subprocess.run(["python", "money_maker_scheduler.py"], capture_output=True, text=True)
    logger.info(f"Full update completed: {result.returncode}")

def run_daily_cleanup():
    logger.info("Running daily cleanup (midnight)...")
    subprocess.run(["find", ".", "-name", "*.log", "-mtime", "+7", "-delete"])
    logger.info("Daily cleanup completed")

if __name__ == "__main__":
    # Schedule tasks
    schedule.every(5).minutes.do(run_quick_update)
    schedule.every(15).minutes.do(run_signal_generation)
    schedule.every().hour.do(run_weather_scan)
    schedule.every(6).hours.do(run_full_update)
    schedule.every().day.at("00:00").do(run_daily_cleanup)

    logger.info("Scheduler started with all tasks configured")
    
    while True:
        schedule.run_pending()
        time.sleep(60)
