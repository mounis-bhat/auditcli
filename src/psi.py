"""PSI/CrUX fetcher - fetches real user metrics from PageSpeed Insights."""

import os
from typing import Any, Callable, Dict, Optional, cast

import httpx
from dotenv import load_dotenv

from src.models import CrUXData, CrUXMetric, MetricDistribution, Rating

PSI_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


# === Rating Functions ===


def _rate_lcp(lcp_ms: float) -> Rating:
    if lcp_ms <= 2500:
        return Rating.GOOD
    if lcp_ms <= 4000:
        return Rating.NEEDS_IMPROVEMENT
    return Rating.POOR


def _rate_cls(cls: float) -> Rating:
    if cls <= 0.1:
        return Rating.GOOD
    if cls <= 0.25:
        return Rating.NEEDS_IMPROVEMENT
    return Rating.POOR


def _rate_inp(inp_ms: float) -> Rating:
    if inp_ms <= 200:
        return Rating.GOOD
    if inp_ms <= 500:
        return Rating.NEEDS_IMPROVEMENT
    return Rating.POOR


# === Parsing Functions ===


def _parse_distribution(data: Dict[str, Any]) -> Optional[MetricDistribution]:
    """Parse distribution buckets from PSI response."""
    distributions = cast(list[Dict[str, Any]], data.get("distributions", []))
    if not distributions or len(distributions) < 3:
        return None

    return MetricDistribution(
        good=distributions[0].get("proportion", 0),
        needs_improvement=distributions[1].get("proportion", 0),
        poor=distributions[2].get("proportion", 0),
    )


def _parse_metric(
    data: Dict[str, Any],
    metric_key: str,
    rate_func: Optional[Callable[[float], Rating]] = None,
) -> Optional[CrUXMetric]:
    """Parse a single CrUX metric from PSI response."""
    metric_data = data.get(metric_key)
    if not metric_data:
        return None

    p75 = cast(Optional[float], metric_data.get("percentile"))
    distribution = _parse_distribution(metric_data)

    rating = None
    if p75 is not None and rate_func:
        rating = rate_func(p75)

    return CrUXMetric(
        p75=p75,
        distribution=distribution,
        rating=rating,
    )


def _parse_overall_rating(category: Optional[str]) -> Optional[Rating]:
    """Parse overall category to rating."""
    if not category:
        return None
    category_map = {
        "FAST": Rating.GOOD,
        "AVERAGE": Rating.NEEDS_IMPROVEMENT,
        "SLOW": Rating.POOR,
    }
    return category_map.get(category)


def fetch_crux(url: str, timeout: float = 60.0) -> Optional[CrUXData]:
    """
    Fetch CrUX field data from PageSpeed Insights API.
    Returns None if API key missing or no field data available.
    """
    load_dotenv()

    api_key = os.environ.get("PSI_API_KEY")
    if not api_key:
        return None  # No API key, return None (not an error)

    params = {
        "url": url,
        "key": api_key,
        "strategy": "mobile",
        "category": "performance",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(PSI_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return None  # API error, return None

    # Try URL-specific data first, then origin fallback
    loading_exp = data.get("loadingExperience") or data.get("originLoadingExperience")
    if not loading_exp:
        return None

    is_origin_fallback = data.get("loadingExperience") is None
    metrics_data = loading_exp.get("metrics", {})

    if not metrics_data:
        return None

    return CrUXData(
        lcp=_parse_metric(metrics_data, "LARGEST_CONTENTFUL_PAINT_MS", _rate_lcp),
        cls=_parse_metric(metrics_data, "CUMULATIVE_LAYOUT_SHIFT_SCORE", _rate_cls),
        inp=_parse_metric(metrics_data, "INTERACTION_TO_NEXT_PAINT", _rate_inp),
        fcp=_parse_metric(metrics_data, "FIRST_CONTENTFUL_PAINT_MS"),
        ttfb=_parse_metric(metrics_data, "EXPERIMENTAL_TIME_TO_FIRST_BYTE"),
        origin_fallback=is_origin_fallback,
        overall_rating=_parse_overall_rating(loading_exp.get("overall_category")),
    )
