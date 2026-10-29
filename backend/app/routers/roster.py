from fantasy_agent.config import settings
from fantasy_agent.db.models import RosterRecord, UserRecord
from fantasy_agent.my_roster import get_my_roster as _get_my_roster_pipeline
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db
from ..schemas import MyRosterOut, TeamOut

router = APIRouter(tags=["roster"], dependencies=[Depends(get_current_account)])


@router.get("/teams", response_model=list[TeamOut])
def list_teams(league_id: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    league_id = league_id or settings.sleeper_league_id
    rosters = db.query(RosterRecord).filter_by(league_id=league_id).order_by(RosterRecord.roster_id).all()
    if not rosters:
        raise HTTPException(status_code=409, detail="No data yet. Run a sync first.")

    users_by_id = {u.user_id: u for u in db.query(UserRecord).filter_by(league_id=league_id).all()}
    teams = []
    for r in rosters:
        owner = users_by_id.get(r.owner_id)
        team_name = (owner.team_name if owner else None) or r.owner_id or f"Roster {r.roster_id}"
        teams.append({"owner_user_id": r.owner_id or "", "team_name": team_name, "roster_id": r.roster_id})
    return teams


@router.get("/my-roster", response_model=MyRosterOut)
def my_roster(league_id: str | None = None, owner_user_id: str | None = None, db: Session = Depends(get_db)):
    try:
        return _get_my_roster_pipeline(db, league_id=league_id, owner_user_id=owner_user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
