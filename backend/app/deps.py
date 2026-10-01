"""FastAPI dependencies wiring the request lifecycle to fantasy_agent's
existing session factory and Sleeper client."""

from __future__ import annotations

from collections.abc import Iterator

from fantasy_agent.config import settings
from fantasy_agent.db.models import AccountRecord
from fantasy_agent.db.session import get_session
from fantasy_agent.sleeper.client import SleeperClient
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .auth import get_account_for_token


def require_access_code(x_access_code: str | None = Header(default=None)) -> None:
    """Gate for /api/agent/* and /api/sync/* (CLAUDE.md section 5.3) -- a public
    URL that calls the OpenAI API with your key can otherwise run up a bill
    from anyone who finds the link. A no-op when DEMO_ACCESS_CODE isn't set.

    403, not 401: this runs *in addition to* get_current_account, and the
    frontend needs to tell "you're not signed in" (401 -- drop back to the
    landing page) apart from "you're signed in but missing the access code"
    (403 -- show a message, don't sign the user out).
    """
    if settings.demo_access_code and x_access_code != settings.demo_access_code:
        raise HTTPException(status_code=403, detail="Missing or invalid X-Access-Code header.")


def get_db() -> Iterator[Session]:
    # get_session() already commits on success and rolls back on error, so
    # this just has to yield through it.
    with get_session() as session:
        yield session


def get_current_account(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> AccountRecord:
    """Gate for every page but the landing one -- the frontend shows a
    sign-in/create-account screen to anyone without a valid session, and this
    is what actually enforces that server-side (CLAUDE.md section 5.10)."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    account = get_account_for_token(db, token) if token else None
    if account is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return account


def get_sleeper_client() -> Iterator[SleeperClient]:
    # A real dependency (not a plain default argument) so routes that poll
    # Sleeper live -- best-available, player analysis -- can have it swapped
    # for a mock transport in tests without touching the network.
    client = SleeperClient(base_url=settings.sleeper_base_url)
    try:
        yield client
    finally:
        client.close()
