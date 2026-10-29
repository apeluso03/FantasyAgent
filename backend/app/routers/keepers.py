from fantasy_agent.keeper import compute_keeper_candidates
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db
from ..schemas import KeeperCandidateOut

router = APIRouter(tags=["keepers"], dependencies=[Depends(get_current_account)])


@router.get("/keepers", response_model=list[KeeperCandidateOut])
def keepers(league_id: str | None = None, owner_user_id: str | None = None, db: Session = Depends(get_db)):
    try:
        return compute_keeper_candidates(db, league_id=league_id, owner_user_id=owner_user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
