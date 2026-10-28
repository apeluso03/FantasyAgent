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
    _tool_get_player_recent_games,
    _tool_get_power_rankings,
    _tool_get_rankings,
    _tool_get_roster,
    _tool_list_rosters,
    _tool_search_player,
)
from fantasy_agent.player_analysis import GameLine, PlayerAnalysis
from fantasy_agent.rankings.pages import ALL_PAGES, rankings_page
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

    # Same ranks on every horizon's page -- tests that care about which page a
    # tool reads seed their own differences on top (see _rerank).
    for page in ALL_PAGES:
        session.add(RankingRecord(source="fantasypros", page=page, fp_player_id=1, sleeper_player_id="p1",
                                   name="Patrick Mahomes", team="KC", position="QB", rank_ecr=10, pos_rank="QB2"))
        session.add(RankingRecord(source="fantasypros", page=page, fp_player_id=2, sleeper_player_id="p2",
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


def test_get_league_info_says_which_team_is_the_users(session: Session, monkeypatch):
    _seed(session)
    monkeypatch.setattr(settings, "sleeper_owner_user_id", OWNER_B)
    assert _tool_get_league_info(session)["your_team"] == "Sam's Squad"


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
    # No injuries seeded -- the fields should still be present, just empty,
    # so the model can rely on their shape either way.
    assert result["side_a"]["injured_players_given"] == []
    assert result["side_b"]["injured_players_received"] == []


def test_evaluate_trade_surfaces_injury_fields_so_the_model_can_see_them(session: Session):
    _seed(session)
    session.query(PlayerRecord).filter_by(player_id="p1").one().injury_status = "Out"
    session.commit()

    result = _tool_evaluate_trade(
        session, team_a="Robots", team_a_gives=["mahomes"], team_b="Sam's Squad", team_b_gives=["chase"]
    )

    given = result["side_a"]["injured_players_given"]
    assert len(given) == 1
    assert given[0]["name"] == "Patrick Mahomes"
    assert given[0]["status"] == "Out"
    assert given[0]["multiplier"] == 0.75
    assert "Out" in result["side_a"]["reasoning"]


def test_get_power_rankings_ranks_every_team_with_positional_breakdown(session: Session):
    _seed(session)
    result = _tool_get_power_rankings(session)
    ranks = sorted(t["rank"] for t in result["rankings"])
    assert ranks == [1, 2]
    for team in result["rankings"]:
        assert set(team["positional_rank"]) == {"QB", "RB", "WR", "TE"}
        assert "injured_players" in team


def test_get_power_rankings_surfaces_injured_players(session: Session):
    _seed(session)
    session.query(PlayerRecord).filter_by(player_id="p2").one().injury_status = "Questionable"
    session.commit()

    result = _tool_get_power_rankings(session)
    robots_team = next(t for t in result["rankings"] if t["team"] == "The Robots")
    names = [p["name"] for p in robots_team["injured_players"]]
    assert "Bijan Robinson" in names


# --- rankings horizons and league format -----------------------------------


def _rerank(session: Session, page: str, player_id: str, rank: int) -> None:
    session.query(RankingRecord).filter_by(page=page, sleeper_player_id=player_id).one().rank_ecr = rank
    session.commit()


def _add_ranking(session: Session, page: str, player_id: str, name: str, position: str, rank: int) -> None:
    session.add(RankingRecord(source="fantasypros", page=page, fp_player_id=hash((page, player_id)) % 10**6,
                               sleeper_player_id=player_id, name=name, position=position, rank_ecr=rank))
    session.commit()


def test_rankings_default_to_rest_of_season_and_follow_horizon(session: Session):
    _seed(session)
    _rerank(session, rankings_page("ros", superflex=True), "p1", 50)
    _rerank(session, rankings_page("dynasty", superflex=True), "p1", 5)

    def mahomes_rank(**kwargs) -> int:
        result = _tool_get_rankings(session, search="mahomes", **kwargs)
        return result["rankings"][0]["rank_ecr"]

    assert mahomes_rank() == 50
    assert mahomes_rank(horizon="dynasty") == 5


def test_one_qb_league_reads_one_qb_pages(session: Session):
    _seed(session)
    session.get(LeagueRecord, LEAGUE_ID).roster_positions = ["QB", "RB", "WR", "FLEX", "BN"]
    session.commit()
    _rerank(session, rankings_page("dynasty", superflex=False), "p1", 77)

    result = _tool_get_rankings(session, search="mahomes", horizon="dynasty")
    assert result["rankings"][0]["rank_ecr"] == 77
    assert _tool_get_league_info(session)["format"] == "1qb"


def test_missing_rankings_page_is_a_tool_error_not_silent_nones(session: Session):
    _seed(session)
    session.query(RankingRecord).filter_by(page=rankings_page("weekly", superflex=True)).delete()
    session.commit()
    with pytest.raises(ToolError, match="rankings-sync"):
        _tool_get_rankings(session, horizon="weekly")


def test_evaluate_trade_defaults_to_win_now_and_long_term_uses_dynasty(session: Session):
    _seed(session)
    for page in ALL_PAGES:
        _add_ranking(session, page, "p3", "Ja'Marr Chase", "WR", 20)
    # Mahomes: barely rosterable rest-of-season, but the #1 dynasty asset --
    # and the reverse for Chase.
    _rerank(session, rankings_page("ros", superflex=True), "p1", 400)
    _rerank(session, rankings_page("dynasty", superflex=True), "p1", 1)
    _rerank(session, rankings_page("dynasty", superflex=True), "p3", 150)

    args = dict(team_a="Robots", team_a_gives=["mahomes"], team_b="Sam's Squad", team_b_gives=["chase"])
    win_now = _tool_evaluate_trade(session, **args)
    long_term = _tool_evaluate_trade(session, **args, horizon="long_term")

    assert win_now["horizon"] == "win_now"
    assert "favors The Robots" in win_now["verdict"]
    assert long_term["horizon"] == "long_term"
    assert "favors Sam's Squad" in long_term["verdict"]


def test_evaluate_trade_reports_each_sides_standing(session: Session):
    _seed(session)
    result = _tool_evaluate_trade(
        session, team_a="Robots", team_a_gives=["mahomes"], team_b="Sam's Squad", team_b_gives=["chase"]
    )
    assert result["side_a"]["standing"]["record"] == "5-3"
    assert result["side_b"]["standing"]["record"] == "4-4"


def test_evaluate_trade_rejects_unknown_horizon(session: Session):
    _seed(session)
    with pytest.raises(ToolError, match="win_now"):
        _tool_evaluate_trade(
            session, team_a="Robots", team_a_gives=["mahomes"], team_b="Sam's Squad", team_b_gives=["chase"],
            horizon="next_decade",
        )


# --- recent games ----------------------------------------------------------


def test_get_player_recent_games_prefers_the_rostered_fantasy_player(session: Session, monkeypatch):
    _seed(session)
    # Same name: a free-agent QB and a linebacker. The rostered QB (p1) should win
    # without the model having to disambiguate.
    session.add(PlayerRecord(player_id="p8", full_name="Patrick Mahomes", team=None, position="QB"))
    session.add(PlayerRecord(player_id="p9", full_name="Patrick Mahomes", team="DAL", position="LB"))
    session.commit()

    calls = {}

    def fake_analysis(player_id, *, position, games_back):
        calls.update(player_id=player_id, games_back=games_back)
        return PlayerAnalysis(player_id=player_id, season="2026",
                              games=[GameLine(week=7, points_ppr=31.2, stat_line="300 pass yds, 3 pass TD")],
                              avg_points=31.2, blurb="Averaging 31.2 PPR points")

    monkeypatch.setattr("fantasy_agent.agent.tools.get_player_analysis", fake_analysis)
    result = _tool_get_player_recent_games(session, player="mahomes", games=50)

    assert calls == {"player_id": "p1", "games_back": 10}  # capped at 10
    assert result["games"] == [{"week": 7, "points_ppr": 31.2, "stat_line": "300 pass yds, 3 pass TD"}]
    assert result["avg_points_ppr"] == 31.2


def test_get_player_recent_games_unknown_player(session: Session):
    _seed(session)
    with pytest.raises(ToolError, match="No player matches"):
        _tool_get_player_recent_games(session, player="Nobody McFakename")
