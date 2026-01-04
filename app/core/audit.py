"""Main audit orchestration with parallel Lighthouse execution."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from app.core.ai import generate_ai_report
from app.core.lighthouse import run_lighthouse_parallel, run_lighthouse_single
from app.core.psi import fetch_crux
from app.errors.exceptions import APIError, AuditError
from app.schemas.audit import (
    AuditResponse,
    CrUXData,
    Insights,
    LighthouseReport,
)
from app.schemas.common import Status
from app.services.jobs import AuditStage
from app.services.cache import (
    get_cached_result,
    store_result,
    acquire_url_lock,
    release_url_lock,
)
from app.services.browser_pool import BrowserPool


async def run_audit_async(
    url: str,
    browser_pool: BrowserPool,
    timeout: float = 600.0,
    no_cache: bool = False,
    on_stage_start: Optional[Callable[[AuditStage], None]] = None,
    on_stage_complete: Optional[Callable[[AuditStage], None]] = None,
) -> Dict[str, Any]:
    """
    Run a complete web audit asynchronously with parallel Lighthouse execution.

    This is the primary entry point for audits using browser pooling.

    Always attempts:
    - Lighthouse (mobile + desktop) in parallel
    - CrUX field data
    - AI analysis

    Returns structured response with status indicating success/partial/failed.
    Implements graceful degradation for partial failures.

    Uses URL locking to prevent duplicate concurrent audits of the same URL.
    If another audit for the same URL is in progress, this waits for it to
    complete and returns the cached result.

    Args:
        url: The URL to audit
        browser_pool: Browser pool for Lighthouse execution
        timeout: Total timeout for the audit in seconds (default: 600 = 10 minutes)
        no_cache: If True, skip cache check and don't store results (default: False)
        on_stage_start: Callback when a stage starts
        on_stage_complete: Callback when a stage completes
    """
    # Check cache first (unless disabled)
    if not no_cache:
        cached_result = await asyncio.to_thread(get_cached_result, url)
        if cached_result:
            return AuditResponse.model_validate(cached_result).model_dump()

    # Acquire URL lock to prevent duplicate concurrent audits
    # If we had to wait (another audit in progress), check cache again
    was_first = await acquire_url_lock(url)

    try:
        if not was_first and not no_cache:
            # Another audit was running, check if it cached a result
            cached_result = await asyncio.to_thread(get_cached_result, url)
            if cached_result:
                return AuditResponse.model_validate(cached_result).model_dump()

        lighthouse: Optional[LighthouseReport] = None
        crux: Optional[CrUXData] = None
        ai_report = None
        error_messages: List[str] = []
        timing: Dict[str, float] = {}

        # Track stage completion for parallel lighthouse
        mobile_started = False
        desktop_started = False

        def on_mobile_start() -> None:
            nonlocal mobile_started
            mobile_started = True
            if on_stage_start:
                on_stage_start(AuditStage.LIGHTHOUSE_MOBILE)

        def on_mobile_complete() -> None:
            if on_stage_complete:
                on_stage_complete(AuditStage.LIGHTHOUSE_MOBILE)

        def on_desktop_start() -> None:
            nonlocal desktop_started
            desktop_started = True
            if on_stage_start:
                on_stage_start(AuditStage.LIGHTHOUSE_DESKTOP)

        def on_desktop_complete() -> None:
            if on_stage_complete:
                on_stage_complete(AuditStage.LIGHTHOUSE_DESKTOP)

        # Run Lighthouse in parallel (critical component)
        lighthouse_start = time.time()
        try:
            lighthouse = await run_lighthouse_parallel(
                url=url,
                browser_pool=browser_pool,
                timeout=timeout,
                on_mobile_start=on_mobile_start,
                on_mobile_complete=on_mobile_complete,
                on_desktop_start=on_desktop_start,
                on_desktop_complete=on_desktop_complete,
            )
            timing["lighthouse"] = time.time() - lighthouse_start
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
            crux = await asyncio.to_thread(fetch_crux, url, timeout)
            timing["crux"] = time.time() - crux_start
            if on_stage_complete:
                on_stage_complete(AuditStage.CRUX)
        except APIError as e:
            timing["crux"] = time.time() - crux_start
            error_messages.append(f"CrUX: {str(e)}")
            crux = None
        except Exception as e:
            timing["crux"] = time.time() - crux_start
            error_messages.append(f"CrUX unexpected error: {str(e)}")
            crux = None

        # Generate AI report (optional, graceful degradation)
        if on_stage_start:
            on_stage_start(AuditStage.AI_ANALYSIS)
        ai_start = time.time()
        try:
            ai_report = await asyncio.to_thread(
                generate_ai_report, url, lighthouse, crux, timeout
            )
            timing["ai"] = time.time() - ai_start
            if on_stage_complete:
                on_stage_complete(AuditStage.AI_ANALYSIS)
        except APIError as e:
            timing["ai"] = time.time() - ai_start
            error_messages.append(f"AI: {str(e)}")
            ai_report = None
        except Exception as e:
            timing["ai"] = time.time() - ai_start
            error_messages.append(f"AI unexpected error: {str(e)}")
            ai_report = None

        # Determine status
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
                await asyncio.to_thread(store_result, url, result.model_dump())
            except Exception:
                # Caching failure shouldn't break the audit
                pass

        return result.model_dump()

    finally:
        # Always release the URL lock
        release_url_lock(url)


def run_audit(
    url: str,
    timeout: float = 600.0,
    no_cache: bool = False,
    on_stage_start: Optional[Callable[[AuditStage], None]] = None,
    on_stage_complete: Optional[Callable[[AuditStage], None]] = None,
) -> Dict[str, Any]:
    """
    Run a complete web audit for the given URL (legacy synchronous API).

    This is the legacy synchronous API - prefer run_audit_async for new code.

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
