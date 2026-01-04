"""Main audit orchestration with parallel Lighthouse execution."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, cast

from app.core.ai import generate_ai_report
from app.core.lighthouse import run_lighthouse_parallel
from app.core.psi import fetch_crux_async
from app.errors.exceptions import APIError, AuditError
from app.schemas.audit import (
    AuditResponse,
    CrUXData,
    Insights,
    LighthouseReport,
)
from app.schemas.common import Status
from app.services.browser_pool import BrowserPool
from app.services.cache import (
    acquire_url_lock,
    get_cached_result,
    release_url_lock,
    store_result,
)
from app.services.jobs import AuditStage

logger = logging.getLogger(__name__)


async def _run_lighthouse_stage(  # noqa: ASYNC109
    url: str,
    browser_pool: BrowserPool,
    timeout: float,  # noqa: ASYNC109
    on_stage_start: Callable[[AuditStage], None] | None,
    on_stage_complete: Callable[[AuditStage], None] | None,
) -> tuple[LighthouseReport | None, dict[str, float]]:
    """Run Lighthouse audit stage. Returns (lighthouse_report, timing)."""
    timing: dict[str, float] = {}

    def on_mobile_start() -> None:
        if on_stage_start:
            on_stage_start(AuditStage.LIGHTHOUSE_MOBILE)

    def on_mobile_complete() -> None:
        if on_stage_complete:
            on_stage_complete(AuditStage.LIGHTHOUSE_MOBILE)

    def on_desktop_start() -> None:
        if on_stage_start:
            on_stage_start(AuditStage.LIGHTHOUSE_DESKTOP)

    def on_desktop_complete() -> None:
        if on_stage_complete:
            on_stage_complete(AuditStage.LIGHTHOUSE_DESKTOP)

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
        return lighthouse, timing
    except (AuditError, Exception):
        timing["lighthouse"] = time.time() - lighthouse_start
        raise


async def _run_crux_stage(  # noqa: ASYNC109
    url: str,
    timeout: float,  # noqa: ASYNC109
    on_stage_start: Callable[[AuditStage], None] | None,
    on_stage_complete: Callable[[AuditStage], None] | None,
) -> tuple[CrUXData | None, dict[str, float], list[str]]:
    """Run CrUX fetch stage. Returns (crux_data, timing, error_messages)."""
    timing: dict[str, float] = {}
    error_messages: list[str] = []

    if on_stage_start:
        on_stage_start(AuditStage.CRUX)

    crux_start = time.time()
    try:
        crux = await fetch_crux_async(url, timeout)
        timing["crux"] = time.time() - crux_start
        if on_stage_complete:
            on_stage_complete(AuditStage.CRUX)
        return crux, timing, error_messages
    except APIError as e:
        timing["crux"] = time.time() - crux_start
        error_messages.append(f"CrUX: {str(e)}")
        return None, timing, error_messages
    except Exception as e:
        timing["crux"] = time.time() - crux_start
        error_messages.append(f"CrUX unexpected error: {str(e)}")
        return None, timing, error_messages


async def _run_ai_stage(  # noqa: ASYNC109
    url: str,
    lighthouse: LighthouseReport,
    crux: CrUXData | None,
    timeout: float,  # noqa: ASYNC109
    on_stage_start: Callable[[AuditStage], None] | None,
    on_stage_complete: Callable[[AuditStage], None] | None,
) -> tuple[Any | None, dict[str, float], list[str]]:
    """Run AI analysis stage. Returns (ai_report, timing, error_messages)."""
    timing: dict[str, float] = {}
    error_messages: list[str] = []

    if on_stage_start:
        on_stage_start(AuditStage.AI_ANALYSIS)

    ai_start = time.time()
    try:
        ai_report = await asyncio.to_thread(generate_ai_report, url, lighthouse, crux, timeout)
        timing["ai"] = time.time() - ai_start
        if on_stage_complete:
            on_stage_complete(AuditStage.AI_ANALYSIS)
        return ai_report, timing, error_messages
    except APIError as e:
        timing["ai"] = time.time() - ai_start
        error_messages.append(f"AI: {str(e)}")
        return None, timing, error_messages
    except Exception as e:
        timing["ai"] = time.time() - ai_start
        error_messages.append(f"AI unexpected error: {str(e)}")
        return None, timing, error_messages


async def run_audit_async(  # noqa: ASYNC109
    url: str,
    browser_pool: BrowserPool,
    timeout: float = 600.0,  # noqa: ASYNC109
    no_cache: bool = False,
    on_stage_start: Callable[[AuditStage], None] | None = None,
    on_stage_complete: Callable[[AuditStage], None] | None = None,
) -> dict[str, Any]:
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

        # Run stages and collect all timing and error info
        timing: dict[str, float] = {}
        all_errors: list[str] = []

        # Run Lighthouse stage (critical - fails if it errors)
        try:
            lighthouse, lh_timing = await _run_lighthouse_stage(
                url, browser_pool, timeout, on_stage_start, on_stage_complete
            )
            timing.update(lh_timing)
        except (AuditError, Exception) as e:
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

        # Run CrUX stage (optional, graceful degradation)
        crux, crux_timing, crux_errors = await _run_crux_stage(
            url, timeout, on_stage_start, on_stage_complete
        )
        timing.update(crux_timing)
        all_errors.extend(crux_errors)

        # Run AI stage (optional, graceful degradation)
        # lighthouse is guaranteed to be not None here (Lighthouse stage would have returned early otherwise)
        lighthouse_casted = cast(LighthouseReport, lighthouse)
        ai_report, ai_timing, ai_errors = await _run_ai_stage(
            url, lighthouse_casted, crux, timeout, on_stage_start, on_stage_complete
        )
        timing.update(ai_timing)
        all_errors.extend(ai_errors)

        # Determine final status
        all_succeeded = (
            lighthouse_casted.mobile is not None
            and lighthouse_casted.desktop is not None
            and crux is not None
            and ai_report is not None
        )

        status = Status.SUCCESS if all_succeeded else Status.PARTIAL
        error = "; ".join(all_errors) if all_errors else None

        result = AuditResponse(
            status=status,
            url=url,
            lighthouse=lighthouse_casted,
            crux=crux,
            insights=Insights(metrics=lighthouse_casted, ai_report=ai_report),
            error=error,
            timing=timing,
        )

        # Cache successful results (unless disabled)
        if not no_cache and (status == Status.SUCCESS or status == Status.PARTIAL):
            try:
                await asyncio.to_thread(store_result, url, result.model_dump())
            except Exception as e:
                # Caching failure shouldn't break the audit, but log for debugging
                logger.warning(
                    f"Failed to cache audit result for {url}: {e}",
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )

        return result.model_dump()

    finally:
        # Always release the URL lock
        release_url_lock(url)
