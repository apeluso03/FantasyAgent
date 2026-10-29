from fantasy_agent.trade import evaluate_trade as _evaluate_trade_pipeline
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db
from ..schemas import TradeEvaluateIn, TradeEvaluationOut

router = APIRouter(tags=["trade"], dependencies=[Depends(get_current_account)])


@router.post("/trade/evaluate", response_model=TradeEvaluationOut)
def evaluate_trade(body: TradeEvaluateIn, db: Session = Depends(get_db)):
    try:
        return _evaluate_trade_pipeline(
            db, body.side_a_owner, body.side_a_gives, body.side_b_owner, body.side_b_gives, league_id=body.league_id
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
