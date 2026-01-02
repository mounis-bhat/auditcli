"""Pytest fixtures for auditcli tests."""

import pytest

from app.schemas.audit import (
    CategoryScores,
    CoreWebVitals,
    LighthouseMetrics,
    LighthouseReport,
    Opportunity,
)


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
