"""API dependencies for dependency injection."""

from app.config.settings import Config, get_config


def get_settings() -> Config:
    """Get application settings dependency."""
    return get_config()
