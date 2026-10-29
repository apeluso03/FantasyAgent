from fantasy_agent.db.models import LeagueRecord, PlayerRecord, RosterRecord, UserRecord

from .conftest import LEAGUE_ID, OWNER_ID

ROSTER_POSITIONS = ["QB", "RB", "WR", "FLEX", "BN", "BN", "IR"]


def _seed(db) -> None:
    db.add(
        LeagueRecord(
            league_id=LEAGUE_ID, name="L", season="2026", total_rosters=1, roster_positions=ROSTER_POSITIONS
        )
    )
    db.add(UserRecord(user_id=OWNER_ID, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))
    db.add(PlayerRecord(player_id="qb1", full_name="Starter QB", team="KC", position="QB"))
    db.add(PlayerRecord(player_id="rb1", full_name="Starter RB", team="SF", position="RB"))
    db.add(
        RosterRecord(
            league_id=LEAGUE_ID,
            roster_id=1,
            owner_id=OWNER_ID,
            players=["qb1", "rb1"],
            starters=["qb1", "rb1"],
            reserve=[],
            taxi=[],
        )
    )
    db.commit()


def test_teams_requires_synced_data(client):
    resp = client.get("/api/teams")
    assert resp.status_code == 409


def test_teams_lists_rosters(client, db):
    _seed(db)
    resp = client.get("/api/teams")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"owner_user_id": OWNER_ID, "team_name": "Team A", "roster_id": 1}]


def test_my_roster_groups_players(client, db):
    _seed(db)
    resp = client.get("/api/my-roster")
    assert resp.status_code == 200
    body = resp.json()
    assert body["team_name"] == "Team A"
    assert {p["player_id"]: p["group"] for p in body["players"]} == {"qb1": "starter", "rb1": "starter"}


def test_my_roster_missing_data_returns_409(client):
    resp = client.get("/api/my-roster")
    assert resp.status_code == 409
