from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.schemas.audit import AuditResponse
from app.services.jobs import JobStatus, AuditStage


class JobProgress(BaseModel):
    current_stage: Optional[AuditStage] = None
    completed_stages: List[AuditStage] = []
    pending_stages: List[AuditStage] = []


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    url: str
    progress: JobProgress
    result: Optional[AuditResponse] = None  # Full AuditResponse when complete
    error: Optional[str] = None
    created_at: datetime
    queue_position: Optional[int] = None  # Position in queue if status is QUEUED


class PaginatedJobIds(BaseModel):
    items: List[str]
    total: int
    page: int
    per_page: int
    has_next: bool
