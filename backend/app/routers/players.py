from fantasy_agent.db.models import PlayerRecord
from fantasy_agent.player_analysis import get_player_analysis as _get_player_analysis_pipeline
from fantasy_agent.sleeper.client import SleeperAPIError, SleeperClient
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db, get_sleeper_client
from ..schemas import PlayerAnalysisOut, PlayerSearchResultOut

router = APIRouter(tags=["players"], dependencies=[Depends(get_current_account)])


@router.get("/players/search", response_model=list[PlayerSearchResultOut])
def search_players(q: str = Query(..., min_length=1), limit: int = 20, db: Session = Depends(get_db)):
    needle = q.strip().lower()
    matches = [p for p in db.query(PlayerRecord).all() if p.full_name and needle in p.full_name.lower()]
    return matches[:limit]


@router.get("/players/{player_id}/analysis", response_model=PlayerAnalysisOut)
def player_analysis(
    player_id: str,
    games_back: int = 5,
    db: Session = Depends(get_db),
    client: SleeperClient = Depends(get_sleeper_client),
):
    player = db.get(PlayerRecord, player_id)
    try:
        return _get_player_analysis_pipeline(
            player_id, position=player.position if player else None, games_back=games_back, client=client
        )
    except SleeperAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
