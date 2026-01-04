"""PSI/CrUX fetcher - fetches real user metrics from PageSpeed Insights."""

from typing import Any, Callable, Dict, List, Optional, cast

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config.settings import get_config
from app.errors.exceptions import APIError
from app.schemas.audit import CrUXData, CrUXMetric, MetricDistribution
from app.schemas.common import Rating
from app.services.circuit_breaker import get_psi_circuit_breaker

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


# === Type-safe helpers ===


def _safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


# === Parsing Functions ===


def _parse_distribution(data: Dict[str, Any]) -> Optional[MetricDistribution]:
    """Parse distribution buckets from PSI response."""
    raw_distributions = data.get("distributions")
    if raw_distributions is None:
        return None

    # Cast to typed list for proper type inference
    distributions = cast(List[Dict[str, Any]], raw_distributions)
    if len(distributions) < 3:
        return None

    return MetricDistribution(
        good=float(distributions[0].get("proportion", 0)),
        needs_improvement=float(distributions[1].get("proportion", 0)),
        poor=float(distributions[2].get("proportion", 0)),
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

    p75_raw = metric_data.get("percentile")
    p75 = _safe_float(p75_raw)
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
    category_map: Dict[str, Rating] = {
        "FAST": Rating.GOOD,
        "AVERAGE": Rating.NEEDS_IMPROVEMENT,
        "SLOW": Rating.POOR,
    }
    return category_map.get(category)


def _get_loading_experience(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get loading experience data, preferring URL-specific over origin fallback.

    Returns None if no loading experience data is available.
    """
    # Try URL-specific data first
    loading_exp = data.get("loadingExperience")
    if loading_exp and isinstance(loading_exp, dict):
        loading_exp_typed = cast(Dict[str, Any], loading_exp)
        if loading_exp_typed.get("metrics"):
            return loading_exp_typed

    # Fall back to origin data
    origin_exp = data.get("originLoadingExperience")
    if origin_exp and isinstance(origin_exp, dict):
        origin_exp_typed = cast(Dict[str, Any], origin_exp)
        if origin_exp_typed.get("metrics"):
            return origin_exp_typed

    return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(APIError),
)
async def fetch_crux_async(url: str, timeout: float = 60.0) -> Optional[CrUXData]:
    """
    Async version of fetch_crux - fetches CrUX field data from PageSpeed Insights API.

    Returns None if no field data available or circuit is open.
    Raises APIError on API failures (which triggers retry).
    """
    # Check circuit breaker before making request
    circuit_breaker = get_psi_circuit_breaker()
    if not circuit_breaker.can_execute():
        # Circuit is open, fail fast
        return None

    config = get_config()

    params: Dict[str, str] = {
        "url": url,
        "key": config.psi_api_key,
        "strategy": "mobile",
        "category": "performance",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(PSI_API_URL, params=params)
            response.raise_for_status()
            data = response.json()

        # Record success
        circuit_breaker.record_success()

    except httpx.TimeoutException as e:
        circuit_breaker.record_failure()
        raise APIError(f"PSI API request timed out: {e}") from e
    except httpx.HTTPStatusError as e:
        circuit_breaker.record_failure()
        raise APIError(f"PSI API returned error status {e.response.status_code}") from e
    except httpx.RequestError as e:
        circuit_breaker.record_failure()
        raise APIError(f"Failed to connect to PSI API: {e}") from e
    except Exception as e:
        circuit_breaker.record_failure()
        raise APIError(f"Failed to fetch CrUX data: {e}") from e

    # Get loading experience data
    loading_exp = _get_loading_experience(data)
    if not loading_exp:
        return None  # No data available, not an error

    is_origin_fallback = data.get("loadingExperience") is None or not data.get(
        "loadingExperience", {}
    ).get("metrics")
    metrics_data: Dict[str, Any] = loading_exp.get("metrics", {})

    if not metrics_data:
        return None  # No metrics data, not an error

    return CrUXData(
        lcp=_parse_metric(metrics_data, "LARGEST_CONTENTFUL_PAINT_MS", _rate_lcp),
        cls=_parse_metric(metrics_data, "CUMULATIVE_LAYOUT_SHIFT_SCORE", _rate_cls),
        inp=_parse_metric(metrics_data, "INTERACTION_TO_NEXT_PAINT", _rate_inp),
        fcp=_parse_metric(metrics_data, "FIRST_CONTENTFUL_PAINT_MS"),
        ttfb=_parse_metric(metrics_data, "EXPERIMENTAL_TIME_TO_FIRST_BYTE"),
        origin_fallback=is_origin_fallback,
        overall_rating=_parse_overall_rating(loading_exp.get("overall_category")),
    )
