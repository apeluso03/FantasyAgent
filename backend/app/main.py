"""FastAPI app: a new front door onto the unchanged fantasy_agent domain
layer (CLAUDE.md section 3). Routes call the same pipeline functions the CLI
and Tkinter GUIs already use."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fantasy_agent.config import settings
from fantasy_agent.db.session import init_db
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .mock.rooms import rooms
from .routers import agent, auth, draft, keepers, league, mock, players, rankings, roster, sync, trade
from .schemas import HealthOut

APP_VERSION = "0.1.0"

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    # Shows up in the deploy logs -- the quickest way to confirm a host's
    # APP_MODE variable actually reached the process.
    log.warning(
        "App mode: %s (APP_MODE env = %r)", settings.app_mode, os.environ.get("APP_MODE")
    )
    # Fire-and-forget: a fresh deploy (empty Postgres) has no ADP board yet,
    # and the board goes stale as ADP moves. Never blocks startup.
    refresh = asyncio.create_task(asyncio.to_thread(_refresh_stale_mock_board))
    yield
    refresh.cancel()
    await rooms.shutdown()


def _refresh_stale_mock_board() -> None:
    hours = settings.mock_adp_refresh_hours
    if hours <= 0:
        return
    from fantasy_agent.mock_draft.store import ensure_board

    try:
        result = ensure_board(rooms.session_scope, max_age_hours=hours)
        if result is not None:
            log.info("Mock ADP board rebuilt at startup: %s players", result.players)
    except Exception:  # noqa: BLE001 -- the first draft creation retries and reports the error
        log.exception("Startup mock ADP refresh failed")

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
    return {"status": "ok", "version": APP_VERSION, "mode": "mock" if settings.app_mode == "mock" else "full"}


app.include_router(auth.router, prefix="/api")
app.include_router(mock.router, prefix="/api")
# APP_MODE=mock hosts only the mock draft simulator: the league tools (and
# their OpenAI/league-sync costs) simply don't exist on that deployment.
if settings.app_mode != "mock":
    for _router in (league, roster, rankings, keepers, players, sync, trade, draft, agent):
        app.include_router(_router.router, prefix="/api")


# Single-service deploys (Railway): when the built frontend is present, serve
# it from this same app, so the SPA, the REST API and the mock draft
# websockets all share one origin -- no CORS, no cross-origin websocket.
# Dev and the split Vercel/Netlify setup simply don't set FRONTEND_DIST.
_frontend_dist = os.environ.get("FRONTEND_DIST")
if _frontend_dist and Path(_frontend_dist, "index.html").is_file():
    _dist = Path(_frontend_dist).resolve()
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist in candidate.parents:
            return FileResponse(candidate)
        # Every client-side route (/mock/abc, /join/xyz, ...) gets the SPA shell.
        return FileResponse(_dist / "index.html")
