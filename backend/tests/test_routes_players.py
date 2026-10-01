from fantasy_agent.db.models import PlayerRecord


def test_search_players_matches_partial_name(client, db):
    db.add(PlayerRecord(player_id="p1", full_name="Patrick Mahomes", team="KC", position="QB"))
    db.add(PlayerRecord(player_id="p2", full_name="Justin Jefferson", team="MIN", position="WR"))
    db.commit()

    resp = client.get("/api/players/search", params={"q": "mahomes"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["player_id"] == "p1"


def test_search_players_requires_query(client):
    resp = client.get("/api/players/search")
    assert resp.status_code == 422
