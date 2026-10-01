from fantasy_agent.draft import get_best_available as _get_best_available_pipeline
from fantasy_agent.sleeper.client import SleeperAPIError, SleeperClient
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db, get_sleeper_client
from ..schemas import BestAvailablePlayerOut

router = APIRouter(tags=["draft"], dependencies=[Depends(get_current_account)])


@router.get("/draft/best-available", response_model=list[BestAvailablePlayerOut])
def best_available(
    league_id: str | None = None,
    owner_user_id: str | None = None,
    limit: int = 15,
    db: Session = Depends(get_db),
    client: SleeperClient = Depends(get_sleeper_client),
):
    try:
        return _get_best_available_pipeline(
            db, league_id=league_id, owner_user_id=owner_user_id, limit=limit, client=client
        )
    except SleeperAPIError as exc:
        # SleeperAPIError subclasses RuntimeError, so this must be checked first.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
