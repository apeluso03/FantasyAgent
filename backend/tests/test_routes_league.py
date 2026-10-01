from fantasy_agent.db.models import LeagueRecord

from .conftest import LEAGUE_ID


def test_league_not_synced_returns_409(client):
    resp = client.get("/api/league")
    assert resp.status_code == 409
    assert "detail" in resp.json()


def test_league_returns_cached_record(client, db):
    db.add(
        LeagueRecord(
            league_id=LEAGUE_ID,
            name="Test League",
            season="2026",
            total_rosters=12,
            roster_positions=["QB", "RB", "WR", "TE", "FLEX", "BN"],
        )
    )
    db.commit()

    resp = client.get("/api/league")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Test League"
    assert body["total_rosters"] == 12
    assert body["roster_positions"] == ["QB", "RB", "WR", "TE", "FLEX", "BN"]


def test_league_id_query_param_overrides_the_configured_default(client, db):
    db.add(LeagueRecord(league_id=LEAGUE_ID, name="Default League", season="2026", total_rosters=12))
    db.add(LeagueRecord(league_id="other-league", name="A Friend's League", season="2026", total_rosters=10))
    db.commit()

    resp = client.get("/api/league", params={"league_id": "other-league"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "A Friend's League"

    # Omitting it still falls back to the server-configured league.
    resp = client.get("/api/league")
    assert resp.json()["name"] == "Default League"
