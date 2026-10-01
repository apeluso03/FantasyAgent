"""FastAPI app: a new front door onto the unchanged fantasy_agent domain
layer (CLAUDE.md section 3). Routes call the same pipeline functions the CLI
and Tkinter GUIs already use."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fantasy_agent.config import settings
from fantasy_agent.db.session import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import agent, auth, draft, keepers, league, players, rankings, roster, sync, trade
from .schemas import HealthOut

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="FantasyAgent API", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthOut, tags=["health"])
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


app.include_router(auth.router, prefix="/api")
app.include_router(league.router, prefix="/api")
app.include_router(roster.router, prefix="/api")
app.include_router(rankings.router, prefix="/api")
app.include_router(keepers.router, prefix="/api")
app.include_router(players.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(trade.router, prefix="/api")
app.include_router(draft.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
