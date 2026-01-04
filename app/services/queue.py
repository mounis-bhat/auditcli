"""Persistent audit queue backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class QueuedJob:
    """Represents a job waiting in the queue."""

    id: int
    job_id: str
    url: str
    options: dict[str, Any]
    created_at: datetime
    status: str  # pending, processing, cancelled


class PersistentQueue:
    """
    Thread-safe persistent queue for audit jobs.

    Uses SQLite for persistence across restarts.
    """

    _instance: PersistentQueue | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path, max_size: int = 50):
        self.db_path = db_path
        self.max_size = max_size
        self._conn_lock = threading.Lock()
        self._init_table()

    @classmethod
    def get_instance(cls, db_path: Path | None = None, max_size: int = 50) -> PersistentQueue:
        """Get or create the singleton queue instance."""
        with cls._lock:
            if cls._instance is None:
                if db_path is None:
                    raise ValueError("db_path required for first initialization")
                cls._instance = cls(db_path, max_size)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent performance
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_table(self) -> None:
        """Create the queue table if it doesn't exist."""
        with self._conn_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT UNIQUE NOT NULL,
                        url TEXT NOT NULL,
                        options TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'pending'
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON audit_queue(status)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_queue_created ON audit_queue(created_at)"
                )
                conn.commit()
            finally:
                conn.close()

    def enqueue(
        self,
        job_id: str,
        url: str,
        options: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Add a job to the queue.

        Returns the queue position (1-based), or None if queue is full.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                # Check current queue size
                cursor = conn.execute("SELECT COUNT(*) FROM audit_queue WHERE status = 'pending'")
                current_size = cursor.fetchone()[0]

                if current_size >= self.max_size:
                    return None

                # Insert the job
                options_json = json.dumps(options) if options else None
                conn.execute(
                    """
                    INSERT INTO audit_queue (job_id, url, options, status)
                    VALUES (?, ?, ?, 'pending')
                    """,
                    (job_id, url, options_json),
                )
                conn.commit()

                # Return position in queue
                return current_size + 1
            finally:
                conn.close()

    def dequeue(self) -> QueuedJob | None:
        """
        Remove and return the next pending job from the queue.

        Returns None if queue is empty.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                # Get the oldest pending job
                cursor = conn.execute(
                    """
                    SELECT id, job_id, url, options, created_at, status
                    FROM audit_queue
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()

                if row is None:
                    return None

                # Mark as processing
                conn.execute(
                    "UPDATE audit_queue SET status = 'processing' WHERE id = ?",
                    (row["id"],),
                )
                conn.commit()

                # Parse created_at
                created_at = datetime.fromisoformat(row["created_at"])
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)

                return QueuedJob(
                    id=row["id"],
                    job_id=row["job_id"],
                    url=row["url"],
                    options=json.loads(row["options"]) if row["options"] else {},
                    created_at=created_at,
                    status="processing",
                )
            finally:
                conn.close()

    def remove(self, job_id: str) -> bool:
        """
        Remove a job from the queue (completed or cancelled).

        Returns True if job was found and removed.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("DELETE FROM audit_queue WHERE job_id = ?", (job_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def cancel(self, job_id: str) -> bool:
        """
        Mark a queued job as cancelled.

        Returns True if job was found and cancelled.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    UPDATE audit_queue
                    SET status = 'cancelled'
                    WHERE job_id = ? AND status = 'pending'
                    """,
                    (job_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def get_position(self, job_id: str) -> int | None:
        """
        Get the current position of a job in the queue.

        Returns 1-based position, or None if not in queue.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                # Get the job's created_at
                cursor = conn.execute(
                    """
                    SELECT created_at FROM audit_queue
                    WHERE job_id = ? AND status = 'pending'
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                job_created_at = row["created_at"]

                # Count jobs ahead of this one
                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM audit_queue
                    WHERE status = 'pending' AND created_at <= ?
                    """,
                    (job_created_at,),
                )
                return cursor.fetchone()[0]
            finally:
                conn.close()

    def size(self) -> int:
        """Get the number of pending jobs in the queue."""
        with self._conn_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM audit_queue WHERE status = 'pending'")
                return cursor.fetchone()[0]
            finally:
                conn.close()

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        with self._conn_lock:
            conn = self._get_connection()
            try:
                stats = {"pending": 0, "processing": 0, "cancelled": 0}
                cursor = conn.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM audit_queue
                    GROUP BY status
                    """
                )
                for row in cursor:
                    stats[row["status"]] = row["count"]
                return stats
            finally:
                conn.close()

    def cleanup_stale(self, max_age_seconds: int = 3600) -> int:
        """
        Remove stale jobs (processing for too long or old cancelled jobs).

        Returns the number of jobs cleaned up.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    DELETE FROM audit_queue
                    WHERE (status = 'processing' OR status = 'cancelled')
                    AND created_at < datetime('now', ?)
                    """,
                    (f"-{max_age_seconds} seconds",),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def requeue_processing(self) -> int:
        """
        Move processing jobs back to pending (for recovery after crash).

        Returns the number of jobs requeued.
        """
        with self._conn_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    UPDATE audit_queue
                    SET status = 'pending'
                    WHERE status = 'processing'
                    """
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()
