from fantasy_agent.config import settings
from fantasy_agent.db.models import RankingRecord
from fantasy_agent.power_rankings import compute_power_rankings as _compute_power_rankings_pipeline
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db
from ..schemas import RankingOut, TeamPowerRankingOut

router = APIRouter(tags=["rankings"], dependencies=[Depends(get_current_account)])


@router.get("/power-rankings", response_model=list[TeamPowerRankingOut])
def power_rankings(league_id: str | None = None, db: Session = Depends(get_db)):
    try:
        return _compute_power_rankings_pipeline(db, league_id=league_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/rankings", response_model=list[RankingOut])
def rankings(search: str | None = None, limit: int = 25, db: Session = Depends(get_db)):
    page = settings.fantasypros_ranking_page
    query = db.query(RankingRecord).filter_by(source="fantasypros", page=page)
    if search:
        needle = search.lower()
        rows = [r for r in query.all() if needle in r.name.lower()]
    else:
        rows = query.order_by(RankingRecord.rank_ecr).all()
    return rows[:limit]
