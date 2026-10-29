"""In-memory sync job tracking (Phase 2, per CLAUDE.md section 5.6).

Deliberately simple: a dict keyed by UUID, guarded by a lock since the
background task runs on a thread-pool thread (Starlette's BackgroundTasks
offload a sync callable via run_in_threadpool) while /api/jobs/{id} reads
from the request thread. This loses state on restart and doesn't work across
multiple server processes -- the natural upgrade is Celery + Redis, matching
FileFlow's setup, which is the "why" story this is meant to set up.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class Job:
    job_id: str
    kind: str
    status: JobStatus = "pending"
    error: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def is_kind_running(kind: str) -> bool:
    with _lock:
        return any(j.kind == kind and j.status in ("pending", "running") for j in _jobs.values())


def create_job(kind: str) -> Job:
    job = Job(job_id=str(uuid.uuid4()), kind=kind)
    with _lock:
        _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def run_job(job_id: str, fn: Callable[[], None]) -> None:
    with _lock:
        job = _jobs[job_id]
        job.status = "running"
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 -- surfaced to the client via GET /api/jobs/{id}, not raised
        with _lock:
            job.status = "failed"
            job.error = str(exc)
        return
    with _lock:
        job.status = "done"
