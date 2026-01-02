"""Audit endpoints."""

import asyncio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.api.v1.deps import get_job_store
from app.core.audit import run_audit
from app.errors.exceptions import ValidationError
from app.schemas.audit import AuditRequest, AuditResponse
from app.schemas.job import (
    AuditStage,
    JobCreateResponse,
    JobProgress,
    JobStatusResponse,
    JobStatus,
)
from app.services.jobs import JobStore
from app.services.validators import validate_url

router = APIRouter()


async def run_audit_job(job_id: str, url: str, timeout: int, no_cache: bool):
    """Background task to run the audit synchronously."""
    job_store = get_job_store()

    # Periodic cleanup of expired jobs
    job_store.cleanup_expired()

    def on_stage_start(stage: AuditStage):
        job_store.update_stage(job_id, stage)

    def on_stage_complete(stage: AuditStage):
        job_store.complete_stage(job_id, stage)

    try:
        # Run sync audit in thread pool
        result = await asyncio.to_thread(
            run_audit,
            url=url,
            timeout=timeout,
            no_cache=no_cache,
            on_stage_start=on_stage_start,
            on_stage_complete=on_stage_complete,
        )
        job_store.complete_job(job_id, result)
    except Exception as e:
        job_store.fail_job(job_id, str(e))


@router.post("/audit", response_model=JobCreateResponse)
async def create_audit(
    request: AuditRequest,
    background_tasks: BackgroundTasks,
    req: Request,
    job_store: JobStore = Depends(get_job_store),
) -> JobCreateResponse:
    """
    Create an async audit job for the given URL.

    Returns job_id immediately, use GET /audit/{job_id} to check status.
    """
    try:
        # Validate and normalize URL
        validated_url = validate_url(request.url)

        # Check rate limit
        client_ip = req.client.host if req.client else "unknown"
        job_id = job_store.create_job(validated_url, client_ip)
        if job_id is None:
            raise HTTPException(
                status_code=429, detail="Too many active jobs. Try again later."
            )

        # Start background audit
        background_tasks.add_task(
            run_audit_job,
            job_id=job_id,
            url=validated_url,
            timeout=int(request.timeout or 600),
            no_cache=request.no_cache or False,
        )

        return JobCreateResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message="Audit job created. Poll GET /v1/audit/{job_id} for status.",
        )

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/audit/{job_id}", response_model=JobStatusResponse)
async def get_audit_status(
    job_id: str, job_store: JobStore = Depends(get_job_store)
) -> JobStatusResponse:
    """
    Get the status and results of an audit job.

    Returns job status, progress, and results when complete.
    """
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")

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
    )
