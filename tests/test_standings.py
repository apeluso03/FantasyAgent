"""Standings and the playoff-outlook heuristic the agent uses to decide a trade
should be judged on long-term value."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, LeagueRecord, RosterRecord, UserRecord
from fantasy_agent.standings import compute_standings, playoff_outlook

LEAGUE_ID = "L1"


@pytest.mark.parametrize(
    "games_back, games_left, in_position, expected",
    [
        (0, 7, True, "in_position"),
        (1, 7, False, "bubble"),
        (2, 7, False, "bubble"),  # 2 back with 7 left is very catchable
        (3, 7, False, "long_shot"),
        (2, 3, False, "long_shot"),
        (4, 3, False, "eliminated"),  # can't make up 4 games in 3
        (1, 0, False, "eliminated"),  # regular season is over
        (1, None, False, "unknown"),
    ],
)
def test_playoff_outlook(games_back, games_left, in_position, expected):
    assert playoff_outlook(games_back, games_left, in_position=in_position) == expected


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(session: Session, records: list[tuple[int, int, int]], **league_settings) -> None:
    """records: (wins, losses, points_for) per team, team i named 'Team i'."""
    settings = {"playoff_teams": 2, "playoff_week_start": 15, "last_scored_leg": 8} | league_settings
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=len(records),
                              roster_positions=[], settings=settings, scoring_settings={}))
    for i, (wins, losses, pf) in enumerate(records):
        session.add(UserRecord(user_id=f"u{i}", league_id=LEAGUE_ID, team_name=f"Team {i}"))
        session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=i, owner_id=f"u{i}", players=[],
                                  settings={"wins": wins, "losses": losses, "fpts": pf}))
    session.commit()


def test_standings_sort_by_record_then_points_and_measure_games_back(session: Session):
    _seed(session, [(4, 4, 900), (6, 2, 800), (6, 2, 950), (1, 7, 700)])
    standings = compute_standings(session, LEAGUE_ID)

    assert [s.team_name for s in standings] == ["Team 2", "Team 1", "Team 0", "Team 3"]  # PF breaks the 6-2 tie
    by_team = {s.team_name: s for s in standings}
    assert by_team["Team 2"].outlook == "in_position"
    assert by_team["Team 0"].games_back == 2  # 4 wins vs the 2nd seed's 6
    assert by_team["Team 0"].games_remaining == 6  # weeks 9-14
    assert by_team["Team 0"].outlook == "bubble"
    assert by_team["Team 3"].outlook == "long_shot"  # 5 back with 6 left


def test_standings_without_playoff_settings_are_unknown(session: Session):
    _seed(session, [(4, 4, 900), (6, 2, 800)], playoff_teams=None)
    assert {s.outlook for s in compute_standings(session, LEAGUE_ID)} == {"unknown"}
