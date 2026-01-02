from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta, timezone
import uuid
import threading

from app.services.websocket import websocket_manager


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditStage(str, Enum):
    LIGHTHOUSE_MOBILE = "lighthouse_mobile"
    LIGHTHOUSE_DESKTOP = "lighthouse_desktop"
    CRUX = "crux"
    AI_ANALYSIS = "ai_analysis"


def _default_completed_stages() -> List[AuditStage]:
    return []


@dataclass
class Job:
    id: str
    status: JobStatus
    url: str
    current_stage: Optional[AuditStage] = None
    completed_stages: List[AuditStage] = field(
        default_factory=_default_completed_stages
    )
    result: Optional[Dict[str, Any]] = None  # Will hold AuditResponse dict
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JobStore:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.ip_limits: Dict[str, set[str]] = {}  # IP -> set of active job_ids
        self.max_jobs_per_ip = 5

    def _get_progress(self, job: Job) -> int:
        """Calculate progress percentage based on completed stages."""
        total_stages = 4  # LIGHTHOUSE_MOBILE, DESKTOP, CRUX, AI
        return int((len(job.completed_stages) / total_stages) * 100)

    @classmethod
    def get_instance(cls) -> "JobStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def create_job(self, url: str, client_ip: str) -> Optional[str]:
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

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self.jobs.get(job_id)

    def update_stage(self, job_id: str, stage: AuditStage):
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.RUNNING
                job.current_stage = stage
                progress = self._get_progress(job)
                websocket_manager.enqueue_broadcast(
                    job_id, stage.value, progress, job.status.value
                )

    def complete_stage(self, job_id: str, stage: AuditStage):
        with self._lock:
            if job := self.jobs.get(job_id):
                job.completed_stages.append(stage)
                progress = self._get_progress(job)
                current_stage = job.current_stage.value if job.current_stage else ""
                websocket_manager.enqueue_broadcast(
                    job_id, current_stage, progress, job.status.value
                )

    def complete_job(self, job_id: str, result: Dict[str, Any]):
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.COMPLETED
                job.result = result
                job.current_stage = None
                progress = 100
                websocket_manager.enqueue_broadcast(
                    job_id, "", progress, job.status.value
                )
                # Remove from IP tracking
                for ip_jobs in self.ip_limits.values():
                    ip_jobs.discard(job_id)

    def fail_job(self, job_id: str, error: str):
        with self._lock:
            if job := self.jobs.get(job_id):
                job.status = JobStatus.FAILED
                job.error = error
                job.current_stage = None
                progress = self._get_progress(job)
                websocket_manager.enqueue_broadcast(
                    job_id, "", progress, job.status.value
                )
                # Remove from IP tracking
                for ip_jobs in self.ip_limits.values():
                    ip_jobs.discard(job_id)

    def cleanup_expired(self):
        with self._lock:
            expiry_time = datetime.now(timezone.utc) - timedelta(hours=24)
            expired_ids = [
                job_id
                for job_id, job in self.jobs.items()
                if job.created_at < expiry_time
            ]
            for job_id in expired_ids:
                del self.jobs[job_id]
                # Clean up IP tracking
                for ip_jobs in self.ip_limits.values():
                    ip_jobs.discard(job_id)
            # Clean up empty IP sets
            self.ip_limits = {ip: jobs for ip, jobs in self.ip_limits.items() if jobs}
