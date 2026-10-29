from fantasy_agent.config import settings
from fantasy_agent.db.models import LeagueRecord
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db
from ..schemas import LeagueOut

router = APIRouter(tags=["league"], dependencies=[Depends(get_current_account)])


@router.get("/league", response_model=LeagueOut)
def get_league(league_id: str | None = None, db: Session = Depends(get_db)) -> LeagueRecord:
    league = db.get(LeagueRecord, league_id or settings.sleeper_league_id)
    if league is None:
        raise HTTPException(status_code=409, detail="No data yet. Run a sync first.")
    return league
