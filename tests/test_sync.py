import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, PlayerRecord
from fantasy_agent.sleeper.client import SleeperClient
from fantasy_agent.sync import sync_players

FAKE_PLAYERS = {
    "1001": {
        "player_id": "1001",
        "first_name": "Christian",
        "last_name": "McCaffrey",
        "team": "SF",
        "position": "RB",
        "fantasy_positions": ["RB"],
        "status": "Active",
        "active": True,
        "injury_status": "Questionable",
        "injury_body_part": "Achilles",
        "injury_notes": "Limited in practice",
        "injury_start_date": "2026-09-01",
    },
    # Most players have none of the injury fields set -- must stay None, not error.
    "1002": {
        "player_id": "1002",
        "first_name": "Healthy",
        "last_name": "Player",
        "team": "KC",
        "position": "WR",
        "fantasy_positions": ["WR"],
        "status": "Active",
        "active": True,
    },
}


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _client() -> SleeperClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/players/nfl":
            return httpx.Response(200, json=FAKE_PLAYERS)
        return httpx.Response(404, json={"error": "not found"})

    return SleeperClient(base_url="https://sleeper.test", transport=httpx.MockTransport(handler))


def test_sync_players_saves_injury_fields(session: Session):
    count = sync_players(session, _client())
    session.commit()

    assert count == 2

    mccaffrey = session.get(PlayerRecord, "1001")
    assert mccaffrey.injury_status == "Questionable"
    assert mccaffrey.injury_body_part == "Achilles"
    assert mccaffrey.injury_notes == "Limited in practice"
    assert mccaffrey.injury_start_date == "2026-09-01"

    healthy = session.get(PlayerRecord, "1002")
    assert healthy.injury_status is None
    assert healthy.injury_body_part is None
    assert healthy.injury_notes is None
    assert healthy.injury_start_date is None


def test_sync_players_updates_injury_status_on_resync(session: Session):
    # A player who gets hurt between syncs should have their status updated
    # in place on the existing row, not left stale.
    session.add(PlayerRecord(player_id="1001", full_name="Christian McCaffrey", injury_status=None))
    session.commit()

    sync_players(session, _client(), force=True)
    session.commit()

    assert session.get(PlayerRecord, "1001").injury_status == "Questionable"
