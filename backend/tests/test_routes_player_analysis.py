import httpx

from fantasy_agent import player_analysis
from fantasy_agent.db.models import PlayerRecord


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/state/nfl":
        return httpx.Response(200, json={"week": 3, "season": "2026", "season_type": "regular"})
    if path == "/stats/nfl/regular/2026/2":
        return httpx.Response(200, json={"p1": {"pts_ppr": 12.0, "rec": 5, "rec_yd": 60}})
    if path == "/stats/nfl/regular/2026/1":
        return httpx.Response(200, json={"p1": {"pts_ppr": 9.0, "rec": 3, "rec_yd": 30}})
    return httpx.Response(200, text="null", headers={"content-type": "application/json"})


def test_player_analysis_returns_recent_games(client, db, mock_sleeper_client):
    player_analysis._stats_cache.clear()
    db.add(PlayerRecord(player_id="p1", full_name="Some WR", team="XX", position="WR"))
    db.commit()
    mock_sleeper_client(_handler)

    resp = client.get("/api/players/p1/analysis", params={"games_back": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["player_id"] == "p1"
    assert [g["week"] for g in body["games"]] == [2, 1]
    assert body["avg_points"] == 10.5
    player_analysis._stats_cache.clear()


def test_player_analysis_unknown_player_still_returns_blurb(client, mock_sleeper_client):
    mock_sleeper_client(_handler)
    resp = client.get("/api/players/unknown/analysis")
    assert resp.status_code == 200
    assert resp.json()["player_id"] == "unknown"
