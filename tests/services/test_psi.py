"""Tests for PSI/CrUX integration."""

from app.core.psi import _parse_distribution, _parse_metric, _rate_lcp  # type: ignore
from app.schemas.audit import CrUXData, CrUXMetric, MetricDistribution
from app.schemas.common import Rating


class TestCrUXModels:
    """Test CrUX Pydantic models."""

    def test_metric_distribution(self):
        dist = MetricDistribution(good=0.8, needs_improvement=0.15, poor=0.05)
        assert dist.good == 0.8
        assert dist.needs_improvement == 0.15
        assert dist.poor == 0.05

    def test_crux_metric(self):
        metric = CrUXMetric(
            p75=2500,
            distribution=MetricDistribution(good=0.7, needs_improvement=0.2, poor=0.1),
            rating=Rating.GOOD,
        )
        assert metric.p75 == 2500
        assert metric.distribution is not None
        assert metric.distribution.good == 0.7
        assert metric.rating == Rating.GOOD

    def test_crux_data(self):
        data = CrUXData(
            lcp=CrUXMetric(p75=2500, rating=Rating.GOOD),
            cls=CrUXMetric(p75=0.05, rating=Rating.GOOD),
            inp=CrUXMetric(p75=150, rating=Rating.GOOD),
        )
        assert data.lcp is not None
        assert data.lcp.p75 == 2500
        assert data.cls is not None
        assert data.cls.p75 == 0.05
        assert data.inp is not None
        assert data.inp.p75 == 150


class TestParsing:
    """Test PSI response parsing functions."""

    def test_parse_distribution(self):
        data = {
            "distributions": [
                {"proportion": 0.8},
                {"proportion": 0.15},
                {"proportion": 0.05},
            ]
        }
        dist = _parse_distribution(data)
        assert dist is not None
        assert dist.good == 0.8
        assert dist.needs_improvement == 0.15
        assert dist.poor == 0.05

    def test_parse_distribution_empty(self):
        dist = _parse_distribution({})
        assert dist is None

    def test_parse_metric(self):
        from typing import Any, Dict

        data: Dict[str, Any] = {
            "LARGEST_CONTENTFUL_PAINT_MS": {
                "percentile": 2500,
                "distributions": [
                    {"proportion": 0.7},
                    {"proportion": 0.2},
                    {"proportion": 0.1},
                ],
            }
        }
        metric = _parse_metric(data, "LARGEST_CONTENTFUL_PAINT_MS", rate_func=_rate_lcp)
        assert metric is not None
        assert metric.p75 == 2500
        assert metric.rating == Rating.GOOD


class TestRating:
    """Test rating functions."""

    def test_rate_lcp_good(self):
        assert _rate_lcp(2000) == Rating.GOOD
        assert _rate_lcp(2500) == Rating.GOOD

    def test_rate_lcp_needs_improvement(self):
        assert _rate_lcp(2501) == Rating.NEEDS_IMPROVEMENT
        assert _rate_lcp(4000) == Rating.NEEDS_IMPROVEMENT

    def test_rate_lcp_poor(self):
        assert _rate_lcp(4001) == Rating.POOR
        assert _rate_lcp(5000) == Rating.POOR
