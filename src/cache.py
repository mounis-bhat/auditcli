"""SQLite caching for audit results."""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv


# Load environment variables
load_dotenv()
CACHE_DB_PATH = Path("audit_cache.db")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "86400"))  # Default 1 day


def _get_url_hash(url: str) -> str:
    """Generate SHA256 hash for URL."""
    return hashlib.sha256(url.encode()).hexdigest()


def _init_cache_db() -> None:
    """Initialize the cache database with required schema."""
    try:
        with sqlite3.connect(CACHE_DB_PATH) as conn:
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
        if CACHE_DB_PATH.exists():
            CACHE_DB_PATH.unlink()
        # Retry once
        with sqlite3.connect(CACHE_DB_PATH) as conn:
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


def get_cached_result(url: str) -> Optional[Dict[str, Any]]:
    """
    Get cached audit result for URL if it exists and hasn't expired.

    Returns the result dict if valid cache exists, None otherwise.
    """
    try:
        _init_cache_db()
        url_hash = _get_url_hash(url)
        current_time = time.time()

        with sqlite3.connect(CACHE_DB_PATH) as conn:
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
        _init_cache_db()
        url_hash = _get_url_hash(url)
        current_time = time.time()

        result_json = json.dumps(result)

        with sqlite3.connect(CACHE_DB_PATH) as conn:
            # Use INSERT OR REPLACE to handle updates
            conn.execute(
                """
                INSERT OR REPLACE INTO cache
                (url_hash, normalized_url, result_json, created_at, ttl_seconds)
                VALUES (?, ?, ?, ?, ?)
            """,
                (url_hash, url, result_json, current_time, CACHE_TTL_SECONDS),
            )
            conn.commit()
    except (sqlite3.Error, json.JSONDecodeError):
        # If caching fails, silently continue (caching is optional)
        pass


def clear_cache() -> None:
    """Clear all cached results."""
    try:
        if CACHE_DB_PATH.exists():
            CACHE_DB_PATH.unlink()
    except Exception:
        pass


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    try:
        _init_cache_db()
        current_time = time.time()

        with sqlite3.connect(CACHE_DB_PATH) as conn:
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
            db_size = CACHE_DB_PATH.stat().st_size if CACHE_DB_PATH.exists() else 0

        return {
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "expired_entries": total_entries - valid_entries,
            "db_size_bytes": db_size,
            "ttl_seconds": CACHE_TTL_SECONDS,
        }
    except Exception:
        return {
            "total_entries": 0,
            "valid_entries": 0,
            "expired_entries": 0,
            "db_size_bytes": 0,
            "ttl_seconds": CACHE_TTL_SECONDS,
        }
