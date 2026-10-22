"""
Database Initialization - SQLite job status database setup.
"""

import sqlite3
from pathlib import Path


def init_job_status_db(db_path: str = "/app/dbdata/job_status.db"):
    """
    Initialize the job status SQLite database.

    Args:
        db_path: Path to the SQLite database file
    """
    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS job_status (
            job_id TEXT PRIMARY KEY,
            step TEXT NOT NULL,
            progress INTEGER NOT NULL,
            message TEXT DEFAULT '',
            error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sql TEXT NOT NULL,
            path TEXT NOT NULL
        )
    ''')

    # Create index for faster lookups
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_job_status_updated_at
        ON job_status(updated_at DESC)
    ''')

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_job_status_db()
    print("Job status database initialized.")
