"""SQLite caching for audit results with URL locking and metrics."""

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.config.settings import get_config

# Thread-safe initialization flag
_cache_initialized = False
_cache_lock = threading.Lock()

# URL locks to prevent duplicate concurrent audits
_url_locks: Dict[str, asyncio.Lock] = {}
_url_locks_lock = threading.Lock()

# Cache metrics
_cache_metrics = {
    "hits": 0,
    "misses": 0,
    "stores": 0,
    "lock_acquisitions": 0,
    "lock_waits": 0,
}
_metrics_lock = threading.Lock()


def _get_cache_path() -> Path:
    """Get cache database path from config."""
    return get_config().cache_db_path


def _get_cache_ttl() -> int:
    """Get cache TTL in seconds from config."""
    return get_config().cache_ttl_seconds


def _get_url_hash(url: str) -> str:
    """Generate SHA256 hash for URL."""
    return hashlib.sha256(url.encode()).hexdigest()


def _init_cache_db(db_path: Path) -> None:
    """Initialize the cache database with required schema and WAL mode."""
    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(db_path) as conn:
            # Enable WAL mode for better concurrent write performance
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    url_hash TEXT PRIMARY KEY,
                    normalized_url TEXT,
                    result_json TEXT,
                    created_at TIMESTAMP,
                    ttl_seconds INTEGER
                )
            """)
            # Create index on url_hash for faster lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_url_hash ON cache(url_hash)")
            conn.commit()
    except sqlite3.Error:
        # If database is corrupted, remove and recreate
        if db_path.exists():
            db_path.unlink()
        # Retry once
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            conn.execute("""
                CREATE TABLE cache (
                    url_hash TEXT PRIMARY KEY,
                    normalized_url TEXT,
                    result_json TEXT,
                    created_at TIMESTAMP,
                    ttl_seconds INTEGER
                )
            """)
            conn.execute("CREATE INDEX idx_url_hash ON cache(url_hash)")
            conn.commit()


def _ensure_cache_initialized() -> Path:
    """
    Initialize cache database once (thread-safe).

    Returns the cache database path.
    """
    global _cache_initialized
    db_path = _get_cache_path()

    if _cache_initialized:
        return db_path

    with _cache_lock:
        if _cache_initialized:  # Double-check after acquiring lock
            return db_path
        _init_cache_db(db_path)
        _cache_initialized = True

    return db_path


def _increment_metric(metric: str, value: int = 1) -> None:
    """Thread-safe metric increment."""
    with _metrics_lock:
        _cache_metrics[metric] = _cache_metrics.get(metric, 0) + value


def get_cached_result(url: str) -> Optional[Dict[str, Any]]:
    """
    Get cached audit result for URL if it exists and hasn't expired.

    Returns the result dict if valid cache exists, None otherwise.
    """
    try:
        db_path = _ensure_cache_initialized()
        url_hash = _get_url_hash(url)
        current_time = time.time()

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.execute(
                """
                SELECT result_json, created_at, ttl_seconds
                FROM cache
                WHERE url_hash = ?
            """,
                (url_hash,),
            )

            row = cursor.fetchone()
            if row:
                result_json, created_at, ttl_seconds = row
                # Check if cache has expired
                if current_time - created_at < ttl_seconds:
                    _increment_metric("hits")
                    return json.loads(result_json)

        _increment_metric("misses")
        return None
    except (sqlite3.Error, json.JSONDecodeError):
        _increment_metric("misses")
        # If cache is corrupted, return None (will recreate on next write)
        return None


def store_result(url: str, result: Dict[str, Any]) -> None:
    """
    Store audit result in cache with TTL.

    Args:
        url: The normalized URL
        result: The audit result dict
    """
    try:
        db_path = _ensure_cache_initialized()
        url_hash = _get_url_hash(url)
        current_time = time.time()
        ttl_seconds = _get_cache_ttl()

        result_json = json.dumps(result)

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Use INSERT OR REPLACE to handle updates
            conn.execute(
                """
                INSERT OR REPLACE INTO cache
                (url_hash, normalized_url, result_json, created_at, ttl_seconds)
                VALUES (?, ?, ?, ?, ?)
            """,
                (url_hash, url, result_json, current_time, ttl_seconds),
            )
            conn.commit()
        _increment_metric("stores")
    except (sqlite3.Error, json.JSONDecodeError):
        # If caching fails, silently continue (caching is optional)
        pass


def clear_cache() -> None:
    """Clear all cached results."""
    try:
        db_path = _get_cache_path()
        if db_path.exists():
            db_path.unlink()
        # Also remove WAL and SHM files if they exist
        wal_path = db_path.with_suffix(".db-wal")
        shm_path = db_path.with_suffix(".db-shm")
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()

        # Reset initialization flag so DB is recreated on next use
        global _cache_initialized
        with _cache_lock:
            _cache_initialized = False
    except OSError:
        pass


def cleanup_expired() -> int:
    """
    Remove expired entries from cache.

    Returns:
        Count of removed entries.
    """
    try:
        db_path = _ensure_cache_initialized()
        current_time = time.time()

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # First count how many will be deleted
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM cache
                WHERE (? - created_at) >= ttl_seconds
                """,
                (current_time,),
            )
            count = cursor.fetchone()[0]

            # Then delete them
            conn.execute(
                """
                DELETE FROM cache
                WHERE (? - created_at) >= ttl_seconds
                """,
                (current_time,),
            )
            conn.commit()
            return count
    except sqlite3.Error:
        return 0


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics including hit/miss rates."""
    try:
        db_path = _ensure_cache_initialized()
        current_time = time.time()

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Count total entries
            cursor = conn.execute("SELECT COUNT(*) FROM cache")
            total_entries = cursor.fetchone()[0]

            # Count valid (non-expired) entries
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM cache
                WHERE (? - created_at) < ttl_seconds
            """,
                (current_time,),
            )
            valid_entries = cursor.fetchone()[0]

            # Get database size
            db_size = db_path.stat().st_size if db_path.exists() else 0

        # Get metrics
        with _metrics_lock:
            hits = _cache_metrics.get("hits", 0)
            misses = _cache_metrics.get("misses", 0)
            stores = _cache_metrics.get("stores", 0)
            lock_acquisitions = _cache_metrics.get("lock_acquisitions", 0)
            lock_waits = _cache_metrics.get("lock_waits", 0)

        total_requests = hits + misses
        hit_rate = (hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "expired_entries": total_entries - valid_entries,
            "db_size_bytes": db_size,
            "db_path": str(db_path),
            "ttl_seconds": _get_cache_ttl(),
            "metrics": {
                "hits": hits,
                "misses": misses,
                "stores": stores,
                "hit_rate_percent": round(hit_rate, 2),
                "total_requests": total_requests,
            },
            "url_locking": {
                "active_locks": len(_url_locks),
                "lock_acquisitions": lock_acquisitions,
                "lock_waits": lock_waits,
            },
        }
    except Exception:
        return {
            "total_entries": 0,
            "valid_entries": 0,
            "expired_entries": 0,
            "db_size_bytes": 0,
            "db_path": str(_get_cache_path()),
            "ttl_seconds": _get_cache_ttl(),
            "metrics": {
                "hits": 0,
                "misses": 0,
                "stores": 0,
                "hit_rate_percent": 0.0,
                "total_requests": 0,
            },
            "url_locking": {
                "active_locks": 0,
                "lock_acquisitions": 0,
                "lock_waits": 0,
            },
        }


def reset_cache_state() -> None:
    """Reset cache initialization state (useful for testing)."""
    global _cache_initialized, _cache_metrics
    with _cache_lock:
        _cache_initialized = False
    with _metrics_lock:
        _cache_metrics = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
            "lock_acquisitions": 0,
            "lock_waits": 0,
        }
    with _url_locks_lock:
        _url_locks.clear()


# === URL Locking Functions ===


def get_url_lock(url: str) -> asyncio.Lock:
    """
    Get or create an asyncio lock for a specific URL.

    This prevents duplicate concurrent audits of the same URL.
    The first request acquires the lock and runs the audit,
    subsequent requests wait for the first to complete and use cached results.
    """
    url_hash = _get_url_hash(url)

    with _url_locks_lock:
        if url_hash not in _url_locks:
            _url_locks[url_hash] = asyncio.Lock()
        return _url_locks[url_hash]


async def acquire_url_lock(url: str) -> bool:
    """
    Acquire the lock for a URL.

    Returns True if lock was acquired immediately (first requester),
    False if we had to wait (another audit was in progress).
    """
    lock = get_url_lock(url)

    # Check if lock is already held (we'll need to wait)
    was_locked = lock.locked()

    if was_locked:
        _increment_metric("lock_waits")

    await lock.acquire()
    _increment_metric("lock_acquisitions")

    return not was_locked


def release_url_lock(url: str) -> None:
    """Release the lock for a URL."""
    url_hash = _get_url_hash(url)

    with _url_locks_lock:
        if url_hash in _url_locks:
            lock = _url_locks[url_hash]
            if lock.locked():
                lock.release()


def cleanup_url_locks() -> int:
    """
    Remove URL locks that are no longer held.

    Returns count of removed locks.
    """
    removed = 0
    with _url_locks_lock:
        to_remove = [
            url_hash for url_hash, lock in _url_locks.items() if not lock.locked()
        ]
        for url_hash in to_remove:
            del _url_locks[url_hash]
            removed += 1
    return removed


def check_database_connection() -> Dict[str, Any]:
    """
    Check if the cache database is accessible and healthy.

    Returns a dict with connection status and details.
    """
    try:
        db_path = _ensure_cache_initialized()

        with sqlite3.connect(db_path, timeout=5.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Simple query to verify connection
            cursor = conn.execute("SELECT 1")
            cursor.fetchone()

            # Check integrity
            cursor = conn.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]

            # Get journal mode
            cursor = conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]

        return {
            "connected": True,
            "path": str(db_path),
            "exists": db_path.exists(),
            "integrity": integrity_result,
            "journal_mode": journal_mode,
            "error": None,
        }
    except Exception as e:
        return {
            "connected": False,
            "path": str(_get_cache_path()),
            "exists": _get_cache_path().exists(),
            "integrity": "unknown",
            "journal_mode": "unknown",
            "error": str(e),
        }
