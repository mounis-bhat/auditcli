"""SQLite caching for audit results."""

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import get_config

# Thread-safe initialization flag
_cache_initialized = False
_cache_lock = threading.Lock()


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
    """Initialize the cache database with required schema."""
    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(db_path) as conn:
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
                    return json.loads(result_json)

        return None
    except (sqlite3.Error, json.JSONDecodeError):
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
    except (sqlite3.Error, json.JSONDecodeError):
        # If caching fails, silently continue (caching is optional)
        pass


def clear_cache() -> None:
    """Clear all cached results."""
    try:
        db_path = _get_cache_path()
        if db_path.exists():
            db_path.unlink()
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
    """Get cache statistics."""
    try:
        db_path = _ensure_cache_initialized()
        current_time = time.time()

        with sqlite3.connect(db_path) as conn:
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

        return {
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "expired_entries": total_entries - valid_entries,
            "db_size_bytes": db_size,
            "db_path": str(db_path),
            "ttl_seconds": _get_cache_ttl(),
        }
    except Exception:
        return {
            "total_entries": 0,
            "valid_entries": 0,
            "expired_entries": 0,
            "db_size_bytes": 0,
            "db_path": str(_get_cache_path()),
            "ttl_seconds": _get_cache_ttl(),
        }


def reset_cache_state() -> None:
    """Reset cache initialization state (useful for testing)."""
    global _cache_initialized
    with _cache_lock:
        _cache_initialized = False
