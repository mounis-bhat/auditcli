"""Concurrency management for audit execution."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

from app.config.settings import get_config
from app.services.queue import PersistentQueue


@dataclass
class ConcurrencyStats:
    """Current concurrency statistics."""

    active_audits: int
    max_concurrent_audits: int
    queue_size: int
    max_queue_size: int
    queue_stats: Dict[str, int] = field(default_factory=dict)


class ConcurrencyManager:
    """
    Manages concurrency limits for audits.

    Uses an asyncio semaphore to limit concurrent audits and
    integrates with the persistent queue for overflow.
    """

    _instance: Optional["ConcurrencyManager"] = None
    _lock = threading.Lock()

    def __init__(self, max_concurrent: int, queue: PersistentQueue):
        self.max_concurrent = max_concurrent
        self.queue = queue
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._active_count = 0
        self._count_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ConcurrencyManager":
        """Get or create the singleton concurrency manager."""
        with cls._lock:
            if cls._instance is None:
                config = get_config()
                queue = PersistentQueue.get_instance(
                    db_path=config.cache_db_path,
                    max_size=config.max_queue_size,
                )
                cls._instance = cls(
                    max_concurrent=config.max_concurrent_audits,
                    queue=queue,
                )
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create the semaphore for the current event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    def try_acquire(self) -> bool:
        """
        Try to acquire a slot for an audit (non-blocking).

        Returns True if a slot was acquired, False if at capacity.
        """
        with self._count_lock:
            if self._active_count >= self.max_concurrent:
                return False
            self._active_count += 1
            return True

    def release(self) -> None:
        """Release a slot after an audit completes."""
        with self._count_lock:
            if self._active_count > 0:
                self._active_count -= 1

    async def acquire(self) -> None:
        """Acquire a slot for an audit (blocking until available)."""
        await self._get_semaphore().acquire()
        with self._count_lock:
            self._active_count += 1

    async def release_async(self) -> None:
        """Release a slot after an audit completes (async version)."""
        self._get_semaphore().release()
        with self._count_lock:
            if self._active_count > 0:
                self._active_count -= 1

    @property
    def active_count(self) -> int:
        """Get the current number of active audits."""
        with self._count_lock:
            return self._active_count

    @property
    def has_capacity(self) -> bool:
        """Check if there's capacity for more audits."""
        with self._count_lock:
            return self._active_count < self.max_concurrent

    def get_stats(self) -> ConcurrencyStats:
        """Get current concurrency statistics."""
        with self._count_lock:
            return ConcurrencyStats(
                active_audits=self._active_count,
                max_concurrent_audits=self.max_concurrent,
                queue_size=self.queue.size(),
                max_queue_size=self.queue.max_size,
                queue_stats=self.queue.get_stats(),
            )

    def can_enqueue(self) -> bool:
        """Check if there's room in the queue."""
        return self.queue.size() < self.queue.max_size

    def enqueue_job(
        self, job_id: str, url: str, options: Optional[Dict] = None
    ) -> Optional[int]:
        """
        Enqueue a job for later processing.

        Returns queue position (1-based), or None if queue is full.
        """
        return self.queue.enqueue(job_id, url, options)

    def get_queue_position(self, job_id: str) -> Optional[int]:
        """Get the current queue position for a job."""
        return self.queue.get_position(job_id)

    def recover_from_crash(self) -> int:
        """
        Recover from a crash by requeuing processing jobs.

        Should be called on startup.
        Returns the number of jobs requeued.
        """
        return self.queue.requeue_processing()
