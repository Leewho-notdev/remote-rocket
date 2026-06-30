"""
scraper/scheduler.py
Runs the scrape cycle on a configurable interval.
This is the container's CMD entrypoint.

Interval is set via SCRAPE_INTERVAL_HOURS in .env (default: 12).

To trigger a manual run without waiting for the schedule:
    docker exec remote-rocket-scraper python main.py
"""

import logging
import os
import sys
import time

import schedule

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db
from main import run_scrape

log = logging.getLogger("remote-rocket.scheduler")

SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", 12))


def main() -> None:
    # DB init runs here so it happens before the first scrape
    init_db()

    log.info(f"Scheduler started — scraping every {SCRAPE_INTERVAL_HOURS} hour(s)")

    # Run once immediately on startup so there's data right away
    run_scrape()

    # Then repeat on the configured interval
    schedule.every(SCRAPE_INTERVAL_HOURS).hours.do(run_scrape)

    while True:
        schedule.run_pending()
        time.sleep(60)   # Check the schedule every minute


if __name__ == "__main__":
    main()
