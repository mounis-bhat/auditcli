"""Audit endpoints with concurrency controls and queue management."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.v1.deps import get_browser_pool, get_concurrency_manager, get_job_store
from app.core.audit import run_audit_async
from app.errors.exceptions import ValidationError
from app.schemas.audit import AuditRequest, AuditResponse
from app.schemas.job import (
    JobCreateResponse,
    JobProgress,
    JobStatusResponse,
    PaginatedJobIds,
)
from app.services.browser_pool import BrowserPool
from app.services.concurrency import ConcurrencyManager
from app.services.jobs import AuditStage, JobStatus, JobStore
from app.services.validators import validate_url

logger = logging.getLogger(__name__)

router = APIRouter()


async def run_audit_job(  # noqa: ASYNC109
    job_id: str,
    url: str,
    timeout: int,  # noqa: ASYNC109
    no_cache: bool,
    job_store: JobStore,
    concurrency_manager: ConcurrencyManager,
    browser_pool: BrowserPool,
) -> None:
    """
    Background task to run the audit with concurrency controls.

    After completing, processes the next job from the queue if available.
    """
    try:
        # Define stage callbacks
        def on_stage_start(stage: AuditStage) -> None:
            job_store.update_stage(job_id, stage)

        def on_stage_complete(stage: AuditStage) -> None:
            job_store.complete_stage(job_id, stage)

        # Run the audit using browser pool
        result = await run_audit_async(
            url=url,
            browser_pool=browser_pool,
            timeout=timeout,
            no_cache=no_cache,
            on_stage_start=on_stage_start,
            on_stage_complete=on_stage_complete,
        )
        job_store.complete_job(job_id, result)

    except Exception as e:
        logger.exception(f"Audit job {job_id} failed: {e}")
        job_store.fail_job(job_id, str(e))

    finally:
        # Release concurrency slot
        concurrency_manager.release()

        # Process next job from queue
        await process_next_queued_job(job_store, concurrency_manager, browser_pool)


async def process_next_queued_job(
    job_store: JobStore,
    concurrency_manager: ConcurrencyManager,
    browser_pool: BrowserPool,
) -> None:
    """Process the next job from the queue if there's capacity."""
    # Try to acquire a slot
    if not concurrency_manager.try_acquire():
        return  # No capacity

    # Get next job from queue
    queued_job = concurrency_manager.queue.dequeue()
    if queued_job is None:
        # No jobs in queue, release the slot we just acquired
        concurrency_manager.release()
        return

    # Update job status from QUEUED to RUNNING
    job = job_store.get_job(queued_job.job_id)
    if job is None:
        # Job was removed/expired, release slot and try next
        concurrency_manager.queue.remove(queued_job.job_id)
        concurrency_manager.release()
        await process_next_queued_job(job_store, concurrency_manager, browser_pool)
        return

    # Update status
    job_store.update_job_status_and_position(queued_job.job_id, JobStatus.PENDING, None)

    # Get options
    options = queued_job.options
    timeout = options.get("timeout", 600)
    no_cache = options.get("no_cache", False)

    # Start the audit in background
    asyncio.create_task(
        run_audit_job(
            job_id=queued_job.job_id,
            url=queued_job.url,
            timeout=timeout,
            no_cache=no_cache,
            job_store=job_store,
            concurrency_manager=concurrency_manager,
            browser_pool=browser_pool,
        )
    )

    # Remove from queue after starting
    concurrency_manager.queue.remove(queued_job.job_id)
    logger.info(f"Started queued job {queued_job.job_id} for {queued_job.url}")


@router.post("/audit", response_model=JobCreateResponse)
async def create_audit(
    request: AuditRequest,
    req: Request,
    job_store: JobStore = Depends(get_job_store),  # noqa: B008
    concurrency_manager: ConcurrencyManager = Depends(get_concurrency_manager),  # noqa: B008
    browser_pool: BrowserPool = Depends(get_browser_pool),  # noqa: B008
) -> JobCreateResponse:
    """
    Create an async audit job for the given URL.

    If at max concurrency, the job is queued and will be processed when a slot opens.
    Returns job_id immediately, use GET /audit/{job_id} to check status.
    """
    # Periodic cleanup of expired jobs
    job_store.cleanup_expired()

    try:
        # Validate and normalize URL
        validated_url = validate_url(request.url)

        # Check per-IP rate limit
        client_ip = req.client.host if req.client else "unknown"
        job_id = job_store.create_job(validated_url, client_ip)
        if job_id is None:
            raise HTTPException(
                status_code=429,
                detail="Too many active jobs for this IP. Try again later.",
            )

        timeout = int(request.timeout or 600)
        no_cache = request.no_cache or False

        # Try to acquire a concurrency slot
        if concurrency_manager.try_acquire():
            # Got a slot, start immediately
            asyncio.create_task(
                run_audit_job(
                    job_id=job_id,
                    url=validated_url,
                    timeout=timeout,
                    no_cache=no_cache,
                    job_store=job_store,
                    concurrency_manager=concurrency_manager,
                    browser_pool=browser_pool,
                )
            )

            return JobCreateResponse(
                job_id=job_id,
                status=JobStatus.PENDING,
                message="Audit job created. Poll GET /v1/audit/{job_id} for status.",
            )
        else:
            # No slot available, try to queue
            queue_position = concurrency_manager.enqueue_job(
                job_id=job_id,
                url=validated_url,
                options={"timeout": timeout, "no_cache": no_cache},
            )

            if queue_position is None:
                # Queue is full, reject the request
                # Remove the job we just created
                job_store.remove_job(job_id)

                raise HTTPException(
                    status_code=503,
                    detail="Server at capacity. Queue is full. Try again later.",
                )

            # Update job status to QUEUED
            job_store.update_job_status_and_position(job_id, JobStatus.QUEUED, queue_position)

            return JobCreateResponse(
                job_id=job_id,
                status=JobStatus.QUEUED,
                message=f"Audit job queued at position {queue_position}. Poll GET /v1/audit/{{job_id}} for status.",
            )

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating audit: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}") from e


@router.get("/audit/{job_id}", response_model=JobStatusResponse)
async def get_audit_status(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),  # noqa: B008
    concurrency_manager: ConcurrencyManager = Depends(get_concurrency_manager),  # noqa: B008
) -> JobStatusResponse:
    """
    Get the status and results of an audit job.

    Returns job status, progress, queue position (if queued), and results when complete.
    """
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    # Update queue position if still queued
    queue_position: int | None = None
    if job.status == JobStatus.QUEUED:
        queue_position = concurrency_manager.get_queue_position(job_id)
        # Update stored position
        job_store.update_queue_position(job_id, queue_position)

    # Calculate pending stages
    all_stages = {
        AuditStage.LIGHTHOUSE_MOBILE,
        AuditStage.LIGHTHOUSE_DESKTOP,
        AuditStage.CRUX,
        AuditStage.AI_ANALYSIS,
    }
    completed = set(job.completed_stages)
    pending = all_stages - completed

    progress = JobProgress(
        current_stage=job.current_stage,
        completed_stages=job.completed_stages,
        pending_stages=list(pending),
    )

    result = None
    if job.result is not None:
        result = AuditResponse.model_validate(job.result)

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        url=job.url,
        progress=progress,
        result=result,
        error=job.error,
        created_at=job.created_at,
        queue_position=queue_position,
    )


@router.delete("/audit/{job_id}")
async def cancel_audit(
    job_id: str,
    job_store: JobStore = Depends(get_job_store),  # noqa: B008
    concurrency_manager: ConcurrencyManager = Depends(get_concurrency_manager),  # noqa: B008
) -> dict[str, Any]:
    """
    Cancel a queued audit job.

    Only jobs in QUEUED status can be cancelled.
    """
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    if job.status != JobStatus.QUEUED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status {job.status}. Only queued jobs can be cancelled.",
        )

    # Cancel in queue
    cancelled = concurrency_manager.queue.cancel(job_id)
    if cancelled:
        job_store.update_job_status_and_position(
            job_id, JobStatus.FAILED, None, "Cancelled by user"
        )

    return {"job_id": job_id, "cancelled": cancelled}


@router.get("/audits/running", response_model=PaginatedJobIds)
async def get_running_audits(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    job_store: JobStore = Depends(get_job_store),  # noqa: B008
) -> PaginatedJobIds:
    """
    Get a paginated list of job IDs for all running audits.

    Running audits include jobs with status PENDING, QUEUED, or RUNNING.
    """
    running_jobs = [
        job.id
        for job in job_store.jobs.values()
        if job.status in [JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING]
    ]
    total = len(running_jobs)
    start = (page - 1) * per_page
    end = start + per_page
    items = running_jobs[start:end]
    has_next = end < total
    return PaginatedJobIds(
        items=items, total=total, page=page, per_page=per_page, has_next=has_next
    )


@router.get("/audits/stats")
async def get_audit_stats(
    concurrency_manager: ConcurrencyManager = Depends(get_concurrency_manager),  # noqa: B008
    browser_pool: BrowserPool = Depends(get_browser_pool),  # noqa: B008
) -> dict[str, Any]:
    """
    Get current audit system statistics.

    Returns concurrency stats, queue stats, browser pool stats,
    cache metrics, and circuit breaker states.
    """
    from app.services.cache import get_cache_stats
    from app.services.circuit_breaker import get_all_circuit_breaker_stats

    concurrency_stats = concurrency_manager.get_stats()
    browser_stats = browser_pool.get_stats()
    cache_stats = get_cache_stats()
    circuit_breakers = get_all_circuit_breaker_stats()

    # Format circuit breaker info
    cb_info = {}
    for name, stats in circuit_breakers.items():
        cb_info[name] = {
            "state": stats.state.value,
            "consecutive_failures": stats.consecutive_failures,
            "total_calls": stats.total_calls,
            "total_failures": stats.total_failures,
            "total_successes": stats.total_successes,
        }

    return {
        "concurrency": {
            "active_audits": concurrency_stats.active_audits,
            "max_concurrent_audits": concurrency_stats.max_concurrent_audits,
            "available_slots": concurrency_stats.max_concurrent_audits
            - concurrency_stats.active_audits,
        },
        "queue": {
            "size": concurrency_stats.queue_size,
            "max_size": concurrency_stats.max_queue_size,
            "stats": concurrency_stats.queue_stats,
        },
        "browser_pool": browser_stats,
        "cache": {
            "entries": cache_stats["valid_entries"],
            "hit_rate_percent": cache_stats["metrics"]["hit_rate_percent"],
            "hits": cache_stats["metrics"]["hits"],
            "misses": cache_stats["metrics"]["misses"],
            "active_url_locks": cache_stats["url_locking"]["active_locks"],
        },
        "circuit_breakers": cb_info,
    }
