"""
init_db.py
Initializes the SQLite database by running schema.sql.

Run this once before first use, or any time you need to reset the database.
It is also called automatically when the scraper container starts.

Usage:
    python db/init_db.py
"""

import sqlite3
import os
import sys

DB_PATH     = os.getenv("DB_PATH", "/app/db/jobs.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def init_db(db_path: str = DB_PATH) -> None:
    # Create the db/ directory if it doesn't exist
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if not os.path.exists(SCHEMA_PATH):
        print(f"ERROR: Schema file not found at {SCHEMA_PATH}")
        sys.exit(1)

    with open(SCHEMA_PATH) as f:
        schema = f.read()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema)
        conn.commit()
        print(f"Database initialized at {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
