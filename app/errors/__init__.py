"""Custom exceptions."""

from app.errors.exceptions import (
    APIError,
    AuditError,
    LighthouseNotFoundError,
    ValidationError,
)

__all__ = [
    "AuditError",
    "APIError",
    "ValidationError",
    "LighthouseNotFoundError",
]
