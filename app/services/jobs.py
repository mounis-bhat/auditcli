from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from app.services.websocket import websocket_manager


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"  # Waiting in queue for a concurrency slot
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditStage(str, Enum):
    LIGHTHOUSE_MOBILE = "lighthouse_mobile"
    LIGHTHOUSE_DESKTOP = "lighthouse_desktop"
    CRUX = "crux"
    AI_ANALYSIS = "ai_analysis"


def _default_completed_stages() -> list[AuditStage]:
    return []


@dataclass
class Job:
    id: str
    status: JobStatus
    url: str
    current_stage: AuditStage | None = None
    completed_stages: list[AuditStage] = field(default_factory=_default_completed_stages)
    result: dict[str, Any] | None = None  # Will hold AuditResponse dict
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    queue_position: int | None = None  # Position in queue if status is QUEUED


class JobStore:
    _instance: JobStore | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.ip_limits: dict[str, set[str]] = {}  # IP -> set of active job_ids
        self.max_jobs_per_ip = 5

    def _get_progress(self, job: Job) -> int:
        """Calculate progress percentage based on completed stages."""
        total_stages = 4  # LIGHTHOUSE_MOBILE, DESKTOP, CRUX, AI
        return int((len(job.completed_stages) / total_stages) * 100)

    @classmethod
    def get_instance(cls) -> JobStore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def create_job(self, url: str, client_ip: str) -> str | None:
        with self._lock:
            # Check rate limit
            active_jobs = self.ip_limits.get(client_ip, set())
            if len(active_jobs) >= self.max_jobs_per_ip:
                return None

            job_id = str(uuid.uuid4())
            job = Job(id=job_id, status=JobStatus.PENDING, url=url)
            self.jobs[job_id] = job
            self.ip_limits.setdefault(client_ip, set()).add(job_id)
            return job_id

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self.jobs.get(job_id)

    def update_stage(self, job_id: str, stage: AuditStage) -> None:
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.RUNNING
                job.current_stage = stage
                progress = self._get_progress(job)
                websocket_manager.enqueue_broadcast(job_id, stage.value, progress, job.status.value)

    def complete_stage(self, job_id: str, stage: AuditStage) -> None:
        with self._lock:
            if job := self.jobs.get(job_id):
                job.completed_stages.append(stage)
                progress = self._get_progress(job)
                current_stage = job.current_stage.value if job.current_stage else ""
                websocket_manager.enqueue_broadcast(
                    job_id, current_stage, progress, job.status.value
                )

    def complete_job(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.COMPLETED
                job.result = result
                job.current_stage = None
                progress = 100
                websocket_manager.enqueue_broadcast(job_id, "", progress, job.status.value)
                # Remove from IP tracking
                for ip_jobs in self.ip_limits.values():
                    ip_jobs.discard(job_id)

    def fail_job(self, job_id: str, error: str) -> None:
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.FAILED
                job.error = error
                job.current_stage = None
                progress = self._get_progress(job)
                websocket_manager.enqueue_broadcast(job_id, "", progress, job.status.value)
                # Remove from IP tracking
                for ip_jobs in self.ip_limits.values():
                    ip_jobs.discard(job_id)

    def update_job_status_and_position(
        self,
        job_id: str,
        status: JobStatus,
        queue_position: int | None = None,
        error: str | None = None,
    ) -> bool:
        """Update job status, queue position, and optional error. Returns True if job exists."""
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = status
                job.queue_position = queue_position
                if error is not None:
                    job.error = error
                return True
        return False

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from storage and IP tracking. Returns True if job existed."""
        with self._lock:
            existed = job_id in self.jobs
            if existed:
                del self.jobs[job_id]
            # Always clean up IP tracking
            for ip_jobs in self.ip_limits.values():
                ip_jobs.discard(job_id)
            # Clean up empty IP sets
            self.ip_limits = {ip: jobs for ip, jobs in self.ip_limits.items() if jobs}
            return existed

    def update_queue_position(self, job_id: str, queue_position: int | None) -> bool:
        """Update the queue position for a job. Returns True if job exists."""
        with self._lock:
            if job := self.jobs.get(job_id):
                job.queue_position = queue_position
                return True
        return False

    def cleanup_expired(self) -> None:
        with self._lock:
            expiry_time = datetime.now(UTC) - timedelta(hours=24)
            expired_ids = [
                job_id for job_id, job in self.jobs.items() if job.created_at < expiry_time
            ]
            for job_id in expired_ids:
                del self.jobs[job_id]
                # Clean up IP tracking
                for ip_jobs in self.ip_limits.values():
                    ip_jobs.discard(job_id)
            # Clean up empty IP sets
            self.ip_limits = {ip: jobs for ip, jobs in self.ip_limits.items() if jobs}
