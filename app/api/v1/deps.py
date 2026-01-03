"""API dependencies for dependency injection."""

from app.config.settings import Config, get_config
from app.services.jobs import JobStore
from app.services.concurrency import ConcurrencyManager
from app.services.browser_pool import BrowserPool


def get_settings() -> Config:
    """Get application settings dependency."""
    return get_config()


def get_job_store() -> JobStore:
    """Get job store dependency."""
    return JobStore.get_instance()


def get_concurrency_manager() -> ConcurrencyManager:
    """Get concurrency manager dependency."""
    return ConcurrencyManager.get_instance()


def get_browser_pool() -> BrowserPool:
    """Get browser pool dependency."""
    return BrowserPool.get_instance()
