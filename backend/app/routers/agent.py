from fantasy_agent.agent.core import run_agent_with_trace
from fantasy_agent.config import settings
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_current_account, get_db, require_access_code
from ..schemas import AgentAskIn, AgentResultOut

router = APIRouter(tags=["agent"], dependencies=[Depends(get_current_account), Depends(require_access_code)])


@router.post("/agent/ask", response_model=AgentResultOut)
def ask(body: AgentAskIn, db: Session = Depends(get_db)):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not set on the server.")

    history = [{"role": turn.role, "content": turn.content} for turn in body.history]
    return run_agent_with_trace(body.question, db, history=history)
