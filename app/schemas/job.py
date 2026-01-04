from datetime import datetime

from pydantic import BaseModel

from app.schemas.audit import AuditResponse
from app.services.jobs import AuditStage, JobStatus


class JobProgress(BaseModel):
    current_stage: AuditStage | None = None
    completed_stages: list[AuditStage] = []
    pending_stages: list[AuditStage] = []


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    url: str
    progress: JobProgress
    result: AuditResponse | None = None  # Full AuditResponse when complete
    error: str | None = None
    created_at: datetime
    queue_position: int | None = None  # Position in queue if status is QUEUED


class PaginatedJobIds(BaseModel):
    items: list[str]
    total: int
    page: int
    per_page: int
    has_next: bool
