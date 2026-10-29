from fantasy_agent.db.models import DraftPickRecord, LeagueRecord, PlayerRecord, RankingRecord, RosterRecord

from .conftest import LEAGUE_ID, OWNER_ID, PAGE


def test_keepers_requires_synced_data(client):
    resp = client.get("/api/keepers")
    assert resp.status_code == 409


def test_keepers_ranks_by_value_surplus(client, db):
    db.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12))
    db.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_ID, players=["breakout"]))
    db.add(PlayerRecord(player_id="breakout", full_name="Breakout Guy", team="KC", position="WR"))
    db.add(DraftPickRecord(league_id=LEAGUE_ID, player_id="breakout", source_draft_id="d1",
                            source_season="2025", round=12, pick_no=140, roster_id=1))
    db.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=1, sleeper_player_id="breakout",
                          name="Breakout Guy", team="KC", position="WR", rank_ecr=8, pos_rank="WR3"))
    db.commit()

    resp = client.get("/api/keepers")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Breakout Guy"
    assert body[0]["value_surplus"] > 0
