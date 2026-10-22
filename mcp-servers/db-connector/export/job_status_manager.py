"""
Job Status Manager - SQLite-based job tracking for async operations.
"""

import sqlite3
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List


class JobStatusManager:
    """
    Thread-safe job status manager using SQLite.
    Tracks progress of async operations like CSV exports.
    """

    _lock = threading.Lock()
    _db_path = "/app/dbdata/job_status.db"

    @classmethod
    def set_db_path(cls, path: str):
        """Set the database path."""
        cls._db_path = path

    @classmethod
    def _get_connection(cls) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(cls._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def create_job(cls, job_id: str, sql: str, path: str) -> Dict[str, Any]:
        """
        Create a new job entry.

        Args:
            job_id: Unique job identifier
            sql: SQL query being executed
            path: Output file path

        Returns:
            Created job status dictionary
        """
        now = datetime.utcnow().isoformat()

        with cls._lock:
            conn = cls._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO job_status
                    (job_id, step, progress, message, error, created_at, updated_at, sql, path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (job_id, 'queued', 0, 'Job created', '', now, now, sql, path))
                conn.commit()

                return {
                    'job_id': job_id,
                    'step': 'queued',
                    'progress': 0,
                    'message': 'Job created',
                    'error': '',
                    'created_at': now,
                    'updated_at': now,
                    'sql': sql,
                    'path': path
                }
            finally:
                conn.close()

    @classmethod
    def update_job_status(cls, job_id: str, step: str, progress: int,
                          message: str = '', error: str = '') -> bool:
        """
        Update job status.

        Args:
            job_id: Job identifier
            step: Current step name
            progress: Progress percentage (0-100, or -1 for failed)
            message: Status message
            error: Error message if failed

        Returns:
            True if update successful
        """
        now = datetime.utcnow().isoformat()

        with cls._lock:
            conn = cls._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE job_status
                    SET step = ?, progress = ?, message = ?, error = ?, updated_at = ?
                    WHERE job_id = ?
                ''', (step, progress, message, error, now, job_id))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    @classmethod
    def get_job_status_by_id(cls, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job status by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job status dictionary or None if not found
        """
        with cls._lock:
            conn = cls._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM job_status WHERE job_id = ?', (job_id,))
                row = cursor.fetchone()

                if row:
                    return dict(row)
                return None
            finally:
                conn.close()

    @classmethod
    def get_latest_n_status(cls, n: int) -> List[Dict[str, Any]]:
        """
        Get latest N job statuses.

        Args:
            n: Number of jobs to retrieve

        Returns:
            List of job status dictionaries
        """
        with cls._lock:
            conn = cls._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM job_status
                    ORDER BY updated_at DESC
                    LIMIT ?
                ''', (n,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    @classmethod
    def cleanup_old_jobs(cls, days: int = 7) -> int:
        """
        Remove jobs older than specified days.

        Args:
            days: Age threshold in days

        Returns:
            Number of jobs removed
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        with cls._lock:
            conn = cls._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM job_status
                    WHERE created_at < ?
                ''', (cutoff,))
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()


# Convenience functions for backward compatibility
def create_job(job_id: str, sql: str, path: str) -> Dict[str, Any]:
    """Create a new job entry."""
    return JobStatusManager.create_job(job_id, sql, path)


def update_job_status(job_id: str, step: str, progress: int,
                      message: str = '', error: str = '') -> bool:
    """Update job status."""
    return JobStatusManager.update_job_status(job_id, step, progress, message, error)


async def get_job_status_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job status by ID (async wrapper)."""
    return JobStatusManager.get_job_status_by_id(job_id)


async def get_latest_n_status(n: int) -> List[Dict[str, Any]]:
    """Get latest N job statuses (async wrapper)."""
    return JobStatusManager.get_latest_n_status(n)
