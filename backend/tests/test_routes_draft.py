import httpx

from fantasy_agent.db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord

from .conftest import LEAGUE_ID, OWNER_ID, PAGE


def _seed(db) -> None:
    db.add(
        LeagueRecord(
            league_id=LEAGUE_ID, name="L", season="2026", total_rosters=2,
            roster_positions=["QB", "RB", "BN"],
        )
    )
    db.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_ID, players=["mine"]))
    db.add(PlayerRecord(player_id="mine", full_name="My Guy", team="XX", position="RB"))
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=1, sleeper_player_id="avail",
                          name="Available Guy", team="XX", position="WR", rank_ecr=10, pos_rank="WR1"))
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=2, sleeper_player_id="drafted",
                          name="Already Drafted", team="XX", position="WR", rank_ecr=5, pos_rank="WR0"))
    db.commit()


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == f"/league/{LEAGUE_ID}/drafts":
        return httpx.Response(200, json=[{"draft_id": "d1", "status": "drafting"}])
    if path == "/draft/d1/picks":
        return httpx.Response(200, json=[{"draft_id": "d1", "player_id": "drafted", "round": 1, "pick_no": 1}])
    return httpx.Response(404, text="not mocked")


def test_best_available_excludes_drafted_and_owned(client, db, mock_sleeper_client):
    _seed(db)
    mock_sleeper_client(_handler)

    resp = client.get("/api/draft/best-available", params={"owner_user_id": OWNER_ID})
    assert resp.status_code == 200
    body = resp.json()
    names = [p["name"] for p in body]
    assert "Available Guy" in names
    assert "Already Drafted" not in names


def test_best_available_requires_synced_data(client, mock_sleeper_client):
    mock_sleeper_client(_handler)
    resp = client.get("/api/draft/best-available", params={"owner_user_id": OWNER_ID})
    assert resp.status_code == 409


def test_best_available_maps_sleeper_failure_to_502(client, db, mock_sleeper_client):
    _seed(db)

    def _failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    mock_sleeper_client(_failing)
    resp = client.get("/api/draft/best-available", params={"owner_user_id": OWNER_ID})
    assert resp.status_code == 502
