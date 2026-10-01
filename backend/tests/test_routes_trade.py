from fantasy_agent.db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord

from .conftest import LEAGUE_ID, PAGE

OWNER_A = "ownerA"
OWNER_B = "ownerB"


def _seed(db) -> None:
    db.add(
        LeagueRecord(
            league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12,
            roster_positions=["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "BN", "BN"],
        )
    )
    db.add(UserRecord(user_id=OWNER_A, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))
    db.add(UserRecord(user_id=OWNER_B, league_id=LEAGUE_ID, display_name="B", team_name="Team B"))
    db.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_A, players=["qb_trade"]))
    db.add(RosterRecord(league_id=LEAGUE_ID, roster_id=2, owner_id=OWNER_B, players=["rb_trade"]))
    db.add(PlayerRecord(player_id="qb_trade", full_name="Traded QB", team="XX", position="QB"))
    db.add(PlayerRecord(player_id="rb_trade", full_name="Traded RB", team="XX", position="RB"))
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=1, sleeper_player_id="qb_trade",
                          name="Traded QB", team="XX", position="QB", rank_ecr=50, pos_rank="QB10"))
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=2, sleeper_player_id="rb_trade",
                          name="Traded RB", team="XX", position="RB", rank_ecr=50, pos_rank="RB10"))
    db.commit()


def test_evaluate_trade_matches_cli_pipeline(client, db):
    _seed(db)
    resp = client.post(
        "/api/trade/evaluate",
        json={
            "side_a_owner": OWNER_A,
            "side_a_gives": ["qb_trade"],
            "side_b_owner": OWNER_B,
            "side_b_gives": ["rb_trade"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "fair" in body["verdict"].lower()
    assert body["side_a"]["value_given"] == body["side_b"]["value_received"]
    assert body["side_a"]["team_name"] == "Team A"


def test_evaluate_trade_unknown_owner_returns_409(client, db):
    _seed(db)
    resp = client.post(
        "/api/trade/evaluate",
        json={"side_a_owner": "nobody", "side_a_gives": [], "side_b_owner": OWNER_B, "side_b_gives": []},
    )
    assert resp.status_code == 409


def test_evaluate_trade_player_not_on_roster_returns_400(client, db):
    _seed(db)
    resp = client.post(
        "/api/trade/evaluate",
        json={
            "side_a_owner": OWNER_A,
            "side_a_gives": ["not_owned"],
            "side_b_owner": OWNER_B,
            "side_b_gives": [],
        },
    )
    assert resp.status_code == 400
