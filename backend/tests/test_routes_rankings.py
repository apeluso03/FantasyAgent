from fantasy_agent.db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord

from .conftest import LEAGUE_ID, OWNER_ID, PAGE


def _seed_rankings(db) -> None:
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=1, sleeper_player_id="p1",
                          name="Mahomes", team="KC", position="QB", rank_ecr=1, pos_rank="QB1"))
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=2, sleeper_player_id="p2",
                          name="Jefferson", team="MIN", position="WR", rank_ecr=2, pos_rank="WR1"))
    db.commit()


def test_rankings_search(client, db):
    _seed_rankings(db)
    resp = client.get("/api/rankings", params={"search": "mahomes"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Mahomes"


def test_rankings_without_search_is_sorted(client, db):
    _seed_rankings(db)
    resp = client.get("/api/rankings")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["name"] for r in body] == ["Mahomes", "Jefferson"]


def test_power_rankings_requires_synced_data(client):
    resp = client.get("/api/power-rankings")
    assert resp.status_code == 409


def test_power_rankings_ranks_teams(client, db):
    db.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=1,
                         roster_positions=["QB", "BN"]))
    db.add(UserRecord(user_id=OWNER_ID, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))
    db.add(PlayerRecord(player_id="p1", full_name="Mahomes", team="KC", position="QB"))
    _seed_rankings(db)
    db.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_ID, players=["p1"], starters=["p1"]))
    db.commit()

    resp = client.get("/api/power-rankings")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["team_name"] == "Team A"
    assert body[0]["rank"] == 1
