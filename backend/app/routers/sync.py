import datetime as dt

from fantasy_agent.db.models import SyncMeta
from fantasy_agent.sync import sync_all, sync_rankings_all
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import jobs
from ..deps import get_current_account, get_db, require_access_code
from ..schemas import JobOut, RankingsSyncRequestIn, SyncRequestIn, SyncStatusEntryOut

router = APIRouter(tags=["sync"], dependencies=[Depends(get_current_account), Depends(require_access_code)])


def _as_utc(value: dt.datetime) -> dt.datetime:
    # SQLite doesn't persist tzinfo, so timestamps come back naive -- same
    # reattachment sync.py's _get_last_synced does before comparing/formatting.
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)


@router.get("/sync/status", response_model=list[SyncStatusEntryOut])
def sync_status(db: Session = Depends(get_db)):
    rows = db.query(SyncMeta).all()
    return [{"resource": r.resource, "last_synced_at": _as_utc(r.last_synced_at).isoformat()} for r in rows]


@router.post("/sync", response_model=JobOut, status_code=202)
def start_sync(body: SyncRequestIn, background_tasks: BackgroundTasks):
    if jobs.is_kind_running("sync"):
        raise HTTPException(status_code=409, detail="A sync is already running.")
    job = jobs.create_job("sync")
    background_tasks.add_task(
        jobs.run_job, job.job_id, lambda: sync_all(body.league_id, force_players=body.force_players)
    )
    return job


@router.post("/rankings/sync", response_model=JobOut, status_code=202)
def start_rankings_sync(body: RankingsSyncRequestIn, background_tasks: BackgroundTasks):
    if jobs.is_kind_running("rankings_sync"):
        raise HTTPException(status_code=409, detail="A rankings sync is already running.")
    job = jobs.create_job("rankings_sync")
    background_tasks.add_task(jobs.run_job, job.job_id, lambda: sync_rankings_all(body.page, force=body.force))
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return job
