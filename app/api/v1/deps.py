"""API dependencies for dependency injection."""

from app.config.settings import Config, get_config
from app.services.jobs import JobStore


def get_settings() -> Config:
    """Get application settings dependency."""
    return get_config()


def get_job_store() -> JobStore:
    """Get job store dependency."""
    return JobStore.get_instance()
