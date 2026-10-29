import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import (
    Base,
    DraftPickRecord,
    LeagueRecord,
    PlayerRecord,
    RankingRecord,
    RosterRecord,
)
from fantasy_agent.keeper import compute_keeper_candidates

LEAGUE_ID = "league1"
OWNER_ID = "owner1"
PAGE = "dynasty-superflex"


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
        )
    )
    session.add(
        RosterRecord(
            league_id=LEAGUE_ID,
            roster_id=1,
            owner_id=OWNER_ID,
            players=["breakout", "bust", "elite", "unranked_player"],
        )
    )
    # breakout: undrafted last year (waiver add), now a top-10 overall player -> huge surplus
    session.add(PlayerRecord(player_id="breakout", full_name="Breakout Guy", team="KC", position="WR"))
    session.add(
        RankingRecord(source="fantasypros", page=PAGE, fp_player_id=1, sleeper_player_id="breakout",
                      name="Breakout Guy", team="KC", position="WR", rank_ecr=8, pos_rank="WR3", tier=1)
    )

    # bust: drafted round 1 last year, now ranked poorly -> negative surplus
    session.add(PlayerRecord(player_id="bust", full_name="Bust Guy", team="NYJ", position="RB"))
    session.add(DraftPickRecord(league_id=LEAGUE_ID, player_id="bust", source_draft_id="d1",
                                 source_season="2025", round=1, pick_no=1, roster_id=1))
    session.add(
        RankingRecord(source="fantasypros", page=PAGE, fp_player_id=2, sleeper_player_id="bust",
                      name="Bust Guy", team="NYJ", position="RB", rank_ecr=150, pos_rank="RB40", tier=8)
    )

    # elite: drafted round 1, ranked #3 -> small positive surplus (paying full price for a star)
    session.add(PlayerRecord(player_id="elite", full_name="Elite Guy", team="DET", position="WR"))
    session.add(DraftPickRecord(league_id=LEAGUE_ID, player_id="elite", source_draft_id="d1",
                                 source_season="2025", round=1, pick_no=2, roster_id=1))
    session.add(
        RankingRecord(source="fantasypros", page=PAGE, fp_player_id=3, sleeper_player_id="elite",
                      name="Elite Guy", team="DET", position="WR", rank_ecr=3, pos_rank="WR1", tier=1)
    )

    # unranked_player: no FantasyPros match at all
    session.add(PlayerRecord(player_id="unranked_player", full_name="No Rank Guy", team="FA", position="QB"))

    # A 15-round draft happened, even though these three picks were rounds 1-1.
    session.add(DraftPickRecord(league_id=LEAGUE_ID, player_id="filler", source_draft_id="d1",
                                 source_season="2025", round=15, pick_no=180, roster_id=5))
    session.commit()


def test_ranks_undrafted_breakout_above_expensive_bust(session: Session):
    _seed(session)
    candidates = compute_keeper_candidates(session, league_id=LEAGUE_ID, owner_user_id=OWNER_ID, penalty=2)
    names_in_order = [c.name for c in candidates]
    assert names_in_order.index("Breakout Guy") < names_in_order.index("Elite Guy")
    assert names_in_order.index("Elite Guy") < names_in_order.index("Bust Guy")


def test_unranked_player_sorts_last_with_explanatory_reasoning(session: Session):
    _seed(session)
    candidates = compute_keeper_candidates(session, league_id=LEAGUE_ID, owner_user_id=OWNER_ID, penalty=2)
    assert candidates[-1].name == "No Rank Guy"
    assert candidates[-1].value_surplus is None
    assert "No FantasyPros ranking" in candidates[-1].reasoning


def test_undrafted_player_defaults_to_last_round_and_gets_cheap_cost(session: Session):
    _seed(session)
    candidates = compute_keeper_candidates(session, league_id=LEAGUE_ID, owner_user_id=OWNER_ID, penalty=2)
    breakout = next(c for c in candidates if c.name == "Breakout Guy")
    assert breakout.was_drafted is False
    assert breakout.drafted_round == 15  # max round seen in cached draft picks
    assert breakout.cost_round == 13  # 15 - 2 penalty
    assert breakout.replacement_rank == 13 * 12
    assert breakout.value_surplus == (13 * 12) - 8


def test_cost_round_never_goes_below_one(session: Session):
    _seed(session)
    candidates = compute_keeper_candidates(session, league_id=LEAGUE_ID, owner_user_id=OWNER_ID, penalty=2)
    elite = next(c for c in candidates if c.name == "Elite Guy")
    # drafted round 1, penalty 2 -> would be -1, must clamp to 1
    assert elite.cost_round == 1


def test_missing_league_raises() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        with pytest.raises(RuntimeError, match="sync"):
            compute_keeper_candidates(s, league_id="nope", owner_user_id="nobody")


def test_missing_roster_raises(session: Session):
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12))
    session.commit()
    with pytest.raises(RuntimeError, match="No roster found"):
        compute_keeper_candidates(session, league_id=LEAGUE_ID, owner_user_id="nobody")


def test_missing_draft_history_raises(session: Session):
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12))
    session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_ID, players=[]))
    session.commit()
    with pytest.raises(RuntimeError, match="draft history"):
        compute_keeper_candidates(session, league_id=LEAGUE_ID, owner_user_id=OWNER_ID)
