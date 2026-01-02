"""Common schemas and enums shared across the application."""

from enum import Enum


class Status(str, Enum):
    """Overall audit status."""

    SUCCESS = "success"
    PARTIAL = "partial"  # Some components failed
    FAILED = "failed"


class Rating(str, Enum):
    """Performance rating for metrics."""

    GOOD = "good"
    NEEDS_IMPROVEMENT = "needs_improvement"
    POOR = "poor"
