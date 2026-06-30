"""
scraper/scheduler.py
Runs the scrape cycle on a configurable interval.
This is the container's CMD entrypoint.

Interval is set via SCRAPE_INTERVAL_HOURS in .env (default: 12).

Manual trigger: write a file to /app/db/.scrape_trigger from the Streamlit app.
The scheduler picks it up within 60 seconds and runs a scrape immediately.
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
TRIGGER_FILE = os.getenv("TRIGGER_FILE", "/app/db/.scrape_trigger")


def _check_trigger() -> bool:
    """Return True and remove the trigger file if it exists."""
    if os.path.exists(TRIGGER_FILE):
        try:
            os.remove(TRIGGER_FILE)
        except OSError:
            pass   # Already removed by a race — that's fine
        return True
    return False


def main() -> None:
    init_db()

    log.info(f"Scheduler started — scraping every {SCRAPE_INTERVAL_HOURS} hour(s)")
    log.info(f"Manual trigger file: {TRIGGER_FILE}")

    # Run once immediately on startup so there's data right away
    run_scrape()

    # Then repeat on the configured interval
    schedule.every(SCRAPE_INTERVAL_HOURS).hours.do(run_scrape)

    while True:
        # Check for manual trigger before running scheduled jobs
        if _check_trigger():
            log.info("Manual trigger detected — starting scrape now")
            run_scrape()
            # Reset the schedule timer so we don't double-scrape soon after
            schedule.clear()
            schedule.every(SCRAPE_INTERVAL_HOURS).hours.do(run_scrape)

        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
