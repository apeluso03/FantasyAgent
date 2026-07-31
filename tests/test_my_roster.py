import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from fantasy_agent.my_roster import get_my_roster

LEAGUE_ID = "league1"
OWNER_A = "ownerA"
PAGE = "dynasty-superflex-overall"
ROSTER_POSITIONS = ["QB", "RB", "WR", "FLEX", "BN", "BN", "IR"]


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _player(session, pid, name, position, rank_ecr, fp_id):
    session.add(PlayerRecord(player_id=pid, full_name=name, team="XX", position=position))
    session.add(
        RankingRecord(
            source="fantasypros", page=PAGE, fp_player_id=fp_id, sleeper_player_id=pid,
            name=name, team="XX", position=position, rank_ecr=rank_ecr, pos_rank=f"{position}{rank_ecr}",
        )
    )


def _seed(session: Session) -> None:
    session.add(
        LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=1, roster_positions=ROSTER_POSITIONS)
    )
    session.add(UserRecord(user_id=OWNER_A, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))

    _player(session, "qb1", "Starter QB", "QB", 10, 1)
    _player(session, "rb1", "Starter RB", "RB", 20, 2)
    _player(session, "wr1", "Starter WR", "WR", 30, 3)
    _player(session, "wr2", "Flex WR", "WR", 40, 4)
    _player(session, "bench1", "Bench Guy", "RB", 90, 5)
    _player(session, "hurt1", "Hurt Guy", "WR", 95, 6)

    session.add(
        RosterRecord(
            league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_A,
            players=["qb1", "rb1", "wr1", "wr2", "bench1", "hurt1"],
            starters=["qb1", "rb1", "wr1", "wr2"],
            reserve=["hurt1"],
            taxi=[],
        )
    )
    session.commit()


def test_groups_players_by_starter_bench_ir(session: Session):
    _seed(session)
    roster = get_my_roster(session, league_id=LEAGUE_ID, owner_user_id=OWNER_A)

    groups = {p.player_id: p.group for p in roster.players}
    assert groups["qb1"] == "starter"
    assert groups["wr2"] == "starter"  # filling FLEX
    assert groups["bench1"] == "bench"
    assert groups["hurt1"] == "ir"

    slots = {p.player_id: p.slot for p in roster.players}
    assert slots["qb1"] == "QB"
    assert slots["rb1"] == "RB"
    assert slots["wr1"] == "WR"
    assert slots["wr2"] == "FLEX"
    assert slots["bench1"] is None


def test_team_name_and_ordering(session: Session):
    _seed(session)
    roster = get_my_roster(session, league_id=LEAGUE_ID, owner_user_id=OWNER_A)

    assert roster.team_name == "Team A"
    # Starters first (in real-roster slot order: QB, RB, WR, ..., FLEX), then bench, then IR.
    order = [p.player_id for p in roster.players]
    assert order == ["qb1", "rb1", "wr1", "wr2", "bench1", "hurt1"]


def test_starters_ordered_by_slot_not_by_rank(session: Session) -> None:
    """A worse-ranked QB must still list above a better-ranked RB -- slot
    order (QB, RB, WR, TE, FLEX, SUPER_FLEX, K, DEF) beats rank order."""
    session.add(
        LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=1, roster_positions=ROSTER_POSITIONS)
    )
    session.add(UserRecord(user_id=OWNER_A, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))

    _player(session, "qb1", "Mediocre QB", "QB", 50, 1)  # worse rank than the RB below
    _player(session, "rb1", "Elite RB", "RB", 5, 2)
    _player(session, "wr1", "Starter WR", "WR", 30, 3)
    _player(session, "wr2", "Flex WR", "WR", 40, 4)

    session.add(
        RosterRecord(
            league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_A,
            players=["qb1", "rb1", "wr1", "wr2"],
            starters=["qb1", "rb1", "wr1", "wr2"],
            reserve=[],
            taxi=[],
        )
    )
    session.commit()

    roster = get_my_roster(session, league_id=LEAGUE_ID, owner_user_id=OWNER_A)
    order = [p.player_id for p in roster.players]
    assert order == ["qb1", "rb1", "wr1", "wr2"]


def test_missing_league_raises() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        with pytest.raises(RuntimeError, match="sync"):
            get_my_roster(s, league_id="nope", owner_user_id="x")


def test_missing_roster_raises(session: Session) -> None:
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=0, roster_positions=[]))
    session.commit()
    with pytest.raises(RuntimeError, match="No roster found"):
        get_my_roster(session, league_id=LEAGUE_ID, owner_user_id="nobody")
