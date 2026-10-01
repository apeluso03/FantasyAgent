"""TestClient + in-memory SQLite + get_db override, per CLAUDE.md section 5.9.

Mutates fantasy_agent's global `settings` for the duration of the test
session (database_url, league/owner IDs) the same way the user-edition GUI
does at runtime -- safe here since tests run in their own process and every
fixture seeds data under LEAGUE_ID/OWNER_ID below.
"""

from __future__ import annotations

import httpx
import pytest
from fantasy_agent.config import settings
from fantasy_agent.db import session as fa_db_session
from fantasy_agent.db.models import Base
from fantasy_agent.sleeper.client import SleeperClient
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import jobs as jobs_module
from backend.app.deps import get_db, get_sleeper_client
from backend.app.main import app

LEAGUE_ID = "league1"
OWNER_ID = "owner1"
PAGE = "dynasty-superflex-overall"

settings.sleeper_league_id = LEAGUE_ID
settings.sleeper_owner_user_id = OWNER_ID
settings.fantasypros_ranking_page = PAGE
# Keep main.py's startup-time init_db() off the real data/fantasy_agent.db
# file -- route calls go through the dependency override below instead.
settings.database_url = "sqlite://"
fa_db_session.reset_engine()

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(_engine)
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def _override_get_db():
    session = _TestSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _clean_db():
    # Each test starts from a clean slate -- small fixed set of tables, cheap
    # enough to wipe before every test rather than rolling back a transaction
    # that route calls (running through their own dependency-injected session)
    # wouldn't see anyway.
    session = _TestSession()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_sleeper_client, None)


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs_module._jobs.clear()


TEST_ACCOUNT_EMAIL = "test@example.com"
TEST_ACCOUNT_PASSWORD = "testpassword123"


@pytest.fixture()
def anon_client(_clean_db):
    """An unauthenticated TestClient -- for the auth flow itself (signup,
    login, and the 401-without-a-token cases) everything else's `client`
    fixture below can't exercise."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(anon_client):
    # Every other route is gated behind get_current_account (CLAUDE.md
    # section 5.10), so `client` signs up a throwaway test account once and
    # carries its token on every request -- existing tests don't each need
    # to know auth exists.
    signup = anon_client.post(
        "/api/auth/signup",
        json={"email": TEST_ACCOUNT_EMAIL, "password": TEST_ACCOUNT_PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    anon_client.headers["Authorization"] = f"Bearer {signup.json()['token']}"
    yield anon_client


@pytest.fixture()
def db():
    session = _TestSession()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def mock_sleeper_client():
    """Installs a fake get_sleeper_client dependency backed by an
    httpx.MockTransport, for routes (draft/best-available, player analysis)
    that are deliberately live-polled and must never hit the real network in
    tests. `handler(request) -> httpx.Response`, same shape as the domain
    layer's own SleeperClient tests."""

    def _install(handler):
        def _override():
            # max_retries=1 so a deliberately-failing handler doesn't burn
            # real wall-clock time on the client's retry backoff.
            mock_client = SleeperClient(
                base_url="https://sleeper.test", max_retries=1, transport=httpx.MockTransport(handler)
            )
            try:
                yield mock_client
            finally:
                mock_client.close()

        app.dependency_overrides[get_sleeper_client] = _override

    return _install
