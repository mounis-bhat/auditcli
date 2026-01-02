"""Main audit orchestration."""

import time
from typing import Any, Callable, Dict, List, Optional

from app.core.ai import generate_ai_report
from app.core.lighthouse import run_lighthouse_single
from app.core.psi import fetch_crux
from app.errors.exceptions import APIError, AuditError
from app.schemas.audit import (
    AuditResponse,
    CrUXData,
    Insights,
    LighthouseReport,
)
from app.schemas.common import Status
from app.schemas.job import AuditStage
from app.services.cache import get_cached_result, store_result


def run_audit(
    url: str,
    timeout: float = 600.0,
    no_cache: bool = False,
    on_stage_start: Optional[Callable[["AuditStage"], None]] = None,
    on_stage_complete: Optional[Callable[["AuditStage"], None]] = None,
) -> Dict[str, Any]:
    """
    Run a complete web audit for the given URL.

    Always attempts:
    - Lighthouse (mobile + desktop)
    - CrUX field data
    - AI analysis

    Returns structured response with status indicating success/partial/failed.
    Implements graceful degradation for partial failures.

    Args:
        url: The URL to audit
        timeout: Total timeout for the audit in seconds (default: 600 = 10 minutes)
        no_cache: If True, skip cache check and don't store results (default: False)
    """
    # Check cache first (unless disabled)
    if not no_cache:
        cached_result = get_cached_result(url)
        if cached_result:
            # Return cached result directly
            return AuditResponse.model_validate(cached_result).model_dump()

    lighthouse: Optional[LighthouseReport] = None
    crux: Optional[CrUXData] = None
    ai_report = None
    error_messages: List[str] = []
    timing: Dict[str, float] = {}

    # Run Lighthouse (critical component)
    lighthouse_start = time.time()
    try:
        mobile_metrics = None
        desktop_metrics = None

        # Run mobile lighthouse
        if on_stage_start:
            on_stage_start(AuditStage.LIGHTHOUSE_MOBILE)
        try:
            mobile_metrics = run_lighthouse_single(url, "mobile", timeout=timeout / 2)
            if on_stage_complete:
                on_stage_complete(AuditStage.LIGHTHOUSE_MOBILE)
        except Exception:
            # Mobile failed, but continue to desktop
            pass

        # Run desktop lighthouse
        if on_stage_start:
            on_stage_start(AuditStage.LIGHTHOUSE_DESKTOP)
        try:
            desktop_metrics = run_lighthouse_single(url, "desktop", timeout=timeout / 2)
            if on_stage_complete:
                on_stage_complete(AuditStage.LIGHTHOUSE_DESKTOP)
        except Exception:
            # Desktop failed, but continue
            pass

        lighthouse = LighthouseReport(mobile=mobile_metrics, desktop=desktop_metrics)
        timing["lighthouse"] = time.time() - lighthouse_start

        # If both failed, raise error
        if mobile_metrics is None and desktop_metrics is None:
            raise AuditError("Lighthouse audits failed for both mobile and desktop")
    except AuditError as e:
        error_messages.append(str(e))
        return AuditResponse(
            status=Status.FAILED,
            url=url,
            lighthouse=LighthouseReport(mobile=None, desktop=None),
            crux=None,
            insights=Insights(
                metrics=LighthouseReport(mobile=None, desktop=None), ai_report=None
            ),
            error=str(e),
        ).model_dump()
    except Exception as e:
        error_messages.append(f"Lighthouse error: {str(e)}")
        return AuditResponse(
            status=Status.FAILED,
            url=url,
            lighthouse=LighthouseReport(mobile=None, desktop=None),
            crux=None,
            insights=Insights(
                metrics=LighthouseReport(mobile=None, desktop=None), ai_report=None
            ),
            error=f"Lighthouse failed: {str(e)}",
        ).model_dump()

    # Fetch CrUX data (optional, graceful degradation)
    if on_stage_start:
        on_stage_start(AuditStage.CRUX)
    crux_start = time.time()
    try:
        crux = fetch_crux(url, timeout=timeout)
        timing["crux"] = time.time() - crux_start
        if on_stage_complete:
            on_stage_complete(AuditStage.CRUX)
    except APIError as e:
        timing["crux"] = time.time() - crux_start
        error_messages.append(f"CrUX: {str(e)}")
        crux = None  # Graceful degradation
    except Exception as e:
        timing["crux"] = time.time() - crux_start
        error_messages.append(f"CrUX unexpected error: {str(e)}")
        crux = None

    # Generate AI report (optional, graceful degradation)
    if on_stage_start:
        on_stage_start(AuditStage.AI_ANALYSIS)
    ai_start = time.time()
    try:
        ai_report = generate_ai_report(url, lighthouse, crux, timeout=timeout)
        timing["ai"] = time.time() - ai_start
        if on_stage_complete:
            on_stage_complete(AuditStage.AI_ANALYSIS)
    except APIError as e:
        timing["ai"] = time.time() - ai_start
        error_messages.append(f"AI: {str(e)}")
        ai_report = None  # Graceful degradation
    except Exception as e:
        timing["ai"] = time.time() - ai_start
        error_messages.append(f"AI unexpected error: {str(e)}")
        ai_report = None

    # Determine status
    # - SUCCESS: Everything worked
    # - PARTIAL: Lighthouse worked but CrUX or AI failed
    assert lighthouse is not None
    all_succeeded = (
        lighthouse.mobile is not None
        and lighthouse.desktop is not None
        and crux is not None
        and ai_report is not None
    )

    status = Status.SUCCESS if all_succeeded else Status.PARTIAL
    error = "; ".join(error_messages) if error_messages else None

    result = AuditResponse(
        status=status,
        url=url,
        lighthouse=lighthouse,
        crux=crux,
        insights=Insights(metrics=lighthouse, ai_report=ai_report),
        error=error,
        timing=timing,
    )

    # Cache successful results (unless disabled)
    if not no_cache and (status == Status.SUCCESS or status == Status.PARTIAL):
        try:
            store_result(url, result.model_dump())
        except Exception:
            # Caching failure shouldn't break the audit
            pass

    return result.model_dump()
