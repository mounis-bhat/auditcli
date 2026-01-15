"""Pytest fixtures for auditor tests."""

import os
from collections.abc import Generator
from pathlib import Path

import pytest

from app.config.settings import reset_config
from app.schemas.audit import (
    CategoryScores,
    CoreWebVitals,
    LighthouseMetrics,
    LighthouseReport,
    Opportunity,
)
from app.services.concurrency import ConcurrencyManager
from app.services.jobs import JobStore
from app.services.queue import PersistentQueue


@pytest.fixture(autouse=True, scope="function")
def reset_singletons(tmp_path: Path) -> Generator[None]:
    """Reset all singleton instances for each test."""
    # Set env var for temp cache path
    os.environ["AUDIT_CACHE_PATH"] = str(tmp_path / "audit_cache.db")

    # Reset all singletons before test
    JobStore._instance = None  # pyright: ignore[reportPrivateUsage]
    ConcurrencyManager.reset_instance()
    PersistentQueue.reset_instance()
    reset_config()

    yield

    # Clean up after test
    JobStore._instance = None  # pyright: ignore[reportPrivateUsage]
    ConcurrencyManager.reset_instance()
    PersistentQueue.reset_instance()
    reset_config()


# Also expose as non-autouse for explicit use
@pytest.fixture(scope="function")
def reset_singletons_explicit(tmp_path: Path) -> Generator[None]:
    """Explicitly reset singletons (autouse version exists too)."""
    os.environ["AUDIT_CACHE_PATH"] = str(tmp_path / "audit_cache.db")
    JobStore._instance = None  # pyright: ignore[reportPrivateUsage]
    ConcurrencyManager.reset_instance()
    PersistentQueue.reset_instance()
    reset_config()
    yield
    JobStore._instance = None  # pyright: ignore[reportPrivateUsage]
    ConcurrencyManager.reset_instance()
    PersistentQueue.reset_instance()
    reset_config()


@pytest.fixture
def sample_lighthouse_report() -> LighthouseReport:
    """Sample LighthouseReport fixture for tests."""
    return LighthouseReport(
        mobile=LighthouseMetrics(
            categories=CategoryScores(
                performance=0.85,
                accessibility=0.92,
                best_practices=0.88,
                seo=0.95,
            ),
            vitals=CoreWebVitals(
                lcp_ms=2500,
                cls=0.08,
                inp_ms=180,
                tbt_ms=250,
            ),
            opportunities=[
                Opportunity(
                    id="render-blocking-resources",
                    title="Eliminate render-blocking resources",
                    description="Resources are blocking the first paint.",
                    estimated_savings_ms=500,
                )
            ],
        ),
        desktop=LighthouseMetrics(
            categories=CategoryScores(
                performance=0.92,
                accessibility=0.92,
                best_practices=0.88,
                seo=0.95,
            ),
            vitals=CoreWebVitals(
                lcp_ms=1800,
                cls=0.05,
                inp_ms=120,
                tbt_ms=150,
            ),
            opportunities=[],
        ),
    )
