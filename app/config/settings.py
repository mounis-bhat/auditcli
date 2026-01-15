"""Centralized configuration loading."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Application configuration."""

    # API Keys
    psi_api_key: str
    google_api_key: str

    # Cache settings
    cache_db_path: Path
    cache_ttl_seconds: int

    # Timeouts
    default_timeout: float

    # Concurrency controls
    max_concurrent_audits: int
    max_queue_size: int
    queue_timeout_seconds: int

    # Browser pool settings
    browser_pool_size: int
    browser_launch_timeout: int
    browser_idle_timeout: int


def _get_required_env(key: str) -> str:
    """Get required environment variable or raise."""
    value = os.getenv(key)
    if not value or not value.strip():
        raise ValueError(f"{key} environment variable is required")
    return value.strip()


def _get_optional_env(key: str, default: str) -> str:
    """Get optional environment variable with default."""
    value = os.getenv(key)
    return value.strip() if value else default


def _get_default_cache_path() -> Path:
    """Get default cache path in user's cache directory."""
    cache_dir = Path.home() / ".cache" / "auditor"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "audit_cache.db"


def load_config() -> Config:
    """Load and validate configuration from environment."""
    load_dotenv()
    cache_path_env = os.getenv("AUDIT_CACHE_PATH")
    cache_path = Path(cache_path_env) if cache_path_env else _get_default_cache_path()

    return Config(
        psi_api_key=_get_required_env("PSI_API_KEY"),
        google_api_key=_get_required_env("GOOGLE_API_KEY"),
        cache_db_path=cache_path,
        cache_ttl_seconds=int(_get_optional_env("CACHE_TTL_SECONDS", "86400")),
        default_timeout=float(_get_optional_env("AUDIT_TIMEOUT", "600")),
        # Concurrency controls
        max_concurrent_audits=int(_get_optional_env("MAX_CONCURRENT_AUDITS", "10")),
        max_queue_size=int(_get_optional_env("MAX_QUEUE_SIZE", "50")),
        queue_timeout_seconds=int(_get_optional_env("QUEUE_TIMEOUT_SECONDS", "300")),
        # Browser pool settings
        browser_pool_size=int(_get_optional_env("BROWSER_POOL_SIZE", "5")),
        browser_launch_timeout=int(_get_optional_env("BROWSER_LAUNCH_TIMEOUT", "30")),
        browser_idle_timeout=int(_get_optional_env("BROWSER_IDLE_TIMEOUT", "300")),
    )


# Singleton config instance (lazy loaded)
_config: Config | None = None


def get_config() -> Config:
    """Get the configuration singleton."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset config singleton (useful for testing)."""
    global _config
    _config = None
