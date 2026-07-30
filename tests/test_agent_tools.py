import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.agent.tools import (
    ToolError,
    resolve_owner,
    _resolve_players_on_roster,
    _tool_evaluate_trade,
    _tool_get_keeper_candidates,
    _tool_get_league_info,
    _tool_get_roster,
    _tool_list_rosters,
    _tool_search_player,
)
from fantasy_agent.config import settings
from fantasy_agent.db.models import (
    Base,
    DraftPickRecord,
    LeagueRecord,
    PlayerRecord,
    RankingRecord,
    RosterRecord,
    UserRecord,
)

LEAGUE_ID = settings.sleeper_league_id
OWNER_A = "owner-a"
OWNER_B = "owner-b"
PAGE = settings.fantasypros_ranking_page


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(session: Session) -> None:
    session.add(
        LeagueRecord(
            league_id=LEAGUE_ID,
            name="Test League",
            season="2026",
            total_rosters=12,
            roster_positions=["QB", "RB", "WR", "SUPER_FLEX", "BN"],
            settings={"type": 1, "max_keepers": 1, "trade_deadline": 11},
            scoring_settings={"rec": 1.0},
        )
    )
    session.add(UserRecord(user_id=OWNER_A, league_id=LEAGUE_ID, display_name="alex", team_name="The Robots"))
    session.add(UserRecord(user_id=OWNER_B, league_id=LEAGUE_ID, display_name="sam", team_name="Sam's Squad"))

    session.add(PlayerRecord(player_id="p1", full_name="Patrick Mahomes", team="KC", position="QB"))
    session.add(PlayerRecord(player_id="p2", full_name="Bijan Robinson", team="ATL", position="RB"))
    session.add(PlayerRecord(player_id="p3", full_name="Ja'Marr Chase", team="CIN", position="WR"))

    session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_A, players=["p1", "p2"],
                              settings={"wins": 5, "losses": 3}))
    session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=2, owner_id=OWNER_B, players=["p3"],
                              settings={"wins": 4, "losses": 4}))

    session.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=1, sleeper_player_id="p1",
                               name="Patrick Mahomes", team="KC", position="QB", rank_ecr=10, pos_rank="QB2"))
    session.add(RankingRecord(source="fantasypros", page=PAGE, fp_player_id=2, sleeper_player_id="p2",
                               name="Bijan Robinson", team="ATL", position="RB", rank_ecr=2, pos_rank="RB2"))

    session.add(DraftPickRecord(league_id=LEAGUE_ID, player_id="p1", source_draft_id="d1",
                                 source_season="2025", round=1, pick_no=1, roster_id=1))
    session.add(DraftPickRecord(league_id=LEAGUE_ID, player_id="filler", source_draft_id="d1",
                                 source_season="2025", round=15, pick_no=180, roster_id=1))
    session.commit()


def test_resolve_owner_exact_and_partial(session: Session):
    _seed(session)
    assert resolve_owner(session, "The Robots").user_id == OWNER_A
    assert resolve_owner(session, "robots").user_id == OWNER_A  # case-insensitive substring
    assert resolve_owner(session, "alex").user_id == OWNER_A  # display_name fallback


def test_resolve_owner_no_match_lists_teams(session: Session):
    _seed(session)
    with pytest.raises(ToolError, match="Teams in this league"):
        resolve_owner(session, "Nonexistent Team")


def test_resolve_players_on_roster_by_partial_name(session: Session):
    _seed(session)
    roster = session.query(RosterRecord).filter_by(owner_id=OWNER_A).one()
    ids = _resolve_players_on_roster(session, roster, ["mahomes"])
    assert ids == ["p1"]


def test_resolve_players_not_on_roster_raises(session: Session):
    _seed(session)
    roster = session.query(RosterRecord).filter_by(owner_id=OWNER_A).one()
    with pytest.raises(ToolError, match="not on this roster"):
        _resolve_players_on_roster(session, roster, ["Ja'Marr Chase"])  # on owner B's roster


def test_get_league_info(session: Session):
    _seed(session)
    info = _tool_get_league_info(session)
    assert info["name"] == "Test League"
    assert info["keeper_settings"]["is_keeper_league"] is True
    assert info["keeper_settings"]["max_keepers"] == 1


def test_list_rosters_includes_position_counts(session: Session):
    _seed(session)
    result = _tool_list_rosters(session)
    teams = {t["team_name"]: t for t in result["teams"]}
    assert teams["The Robots"]["position_counts"] == {"QB": 1, "RB": 1}
    assert teams["Sam's Squad"]["roster_size"] == 1


def test_search_player_partial_match(session: Session):
    _seed(session)
    result = _tool_search_player(session, name="mahom")
    assert result["matches"][0]["name"] == "Patrick Mahomes"


def test_get_roster_includes_rankings(session: Session):
    _seed(session)
    result = _tool_get_roster(session, team="Robots")
    by_id = {p["player_id"]: p for p in result["players"]}
    assert by_id["p1"]["rank_ecr"] == 10
    assert by_id["p2"]["pos_rank"] == "RB2"


def test_get_keeper_candidates_defaults_to_configured_owner(session: Session, monkeypatch):
    _seed(session)
    monkeypatch.setattr(settings, "sleeper_owner_user_id", OWNER_A)
    result = _tool_get_keeper_candidates(session)
    names = [c["name"] for c in result["candidates"]]
    assert "Patrick Mahomes" in names


def test_evaluate_trade_resolves_names_and_returns_verdict(session: Session):
    _seed(session)
    result = _tool_evaluate_trade(
        session, team_a="Robots", team_a_gives=["mahomes"], team_b="Sam's Squad", team_b_gives=["chase"]
    )
    assert "verdict" in result
    assert "reasoning" in result["side_a"]
    assert "reasoning" in result["side_b"]
