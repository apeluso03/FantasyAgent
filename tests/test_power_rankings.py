import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from fantasy_agent.power_rankings import compute_power_rankings
from fantasy_agent.trade import adjusted_player_value

LEAGUE_ID = "league1"
OWNER_A = "ownerA"
OWNER_B = "ownerB"
PAGE = "dynasty-superflex"
ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "BN"]


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


def _seed_two_teams(session: Session) -> None:
    session.add(
        LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=2, roster_positions=ROSTER_POSITIONS)
    )
    session.add(UserRecord(user_id=OWNER_A, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))
    session.add(UserRecord(user_id=OWNER_B, league_id=LEAGUE_ID, display_name="B", team_name="Team B"))

    # Team A: two elite QBs (should occupy QB + SUPER_FLEX), thin everywhere else.
    _player(session, "a_qb1", "Elite QB1", "QB", 1, 1)
    _player(session, "a_qb2", "Elite QB2", "QB", 5, 2)
    _player(session, "a_rb1", "A RB1", "RB", 40, 3)
    _player(session, "a_rb2", "A RB2", "RB", 45, 4)
    _player(session, "a_wr1", "A WR1", "WR", 50, 5)
    _player(session, "a_wr2", "A WR2", "WR", 55, 6)
    _player(session, "a_wr3", "A WR3", "WR", 60, 7)
    _player(session, "a_te1", "A TE1", "TE", 65, 8)
    session.add(
        RosterRecord(
            league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_A,
            players=["a_qb1", "a_qb2", "a_rb1", "a_rb2", "a_wr1", "a_wr2", "a_wr3", "a_te1"],
        )
    )

    # Team B: mediocre QB, deep/elite RB corps.
    _player(session, "b_qb1", "B QB1", "QB", 70, 9)
    _player(session, "b_rb1", "Elite RB1", "RB", 2, 10)
    _player(session, "b_rb2", "Elite RB2", "RB", 3, 11)
    _player(session, "b_rb3", "Elite RB3", "RB", 4, 12)
    _player(session, "b_wr1", "B WR1", "WR", 75, 13)
    _player(session, "b_wr2", "B WR2", "WR", 80, 14)
    _player(session, "b_wr3", "B WR3", "WR", 85, 15)
    _player(session, "b_te1", "B TE1", "TE", 90, 16)
    session.add(
        RosterRecord(
            league_id=LEAGUE_ID, roster_id=2, owner_id=OWNER_B,
            players=["b_qb1", "b_rb1", "b_rb2", "b_rb3", "b_wr1", "b_wr2", "b_wr3", "b_te1"],
        )
    )
    session.commit()


def test_superflex_slot_picks_second_qb_over_a_worse_flex_option(session: Session):
    _seed_two_teams(session)
    teams = compute_power_rankings(session, league_id=LEAGUE_ID)
    team_a = next(t for t in teams if t.team_name == "Team A")

    qb_slot = next(s for s in team_a.starters if s.slot == "QB")
    superflex_slot = next(s for s in team_a.starters if s.slot == "SUPER_FLEX")
    assert qb_slot.name == "Elite QB1"
    assert superflex_slot.name == "Elite QB2"  # beats every non-QB option on this roster


def test_teams_ranked_1_and_2_by_starting_lineup_value(session: Session):
    _seed_two_teams(session)
    teams = compute_power_rankings(session, league_id=LEAGUE_ID)
    ranks = sorted(t.rank for t in teams)
    assert ranks == [1, 2]
    # Team A's two elite QBs should make it the stronger overall lineup.
    team_a = next(t for t in teams if t.team_name == "Team A")
    assert team_a.rank == 1


def test_positional_rank_surfaces_team_bs_rb_depth_despite_lower_overall_rank(session: Session):
    _seed_two_teams(session)
    teams = compute_power_rankings(session, league_id=LEAGUE_ID)
    team_a = next(t for t in teams if t.team_name == "Team A")
    team_b = next(t for t in teams if t.team_name == "Team B")

    assert team_b.positional_rank["RB"] == 1
    assert team_a.positional_rank["RB"] == 2
    assert team_a.positional_rank["QB"] == 1
    assert team_b.positional_rank["QB"] == 2


def test_flex_slot_filled_from_remaining_rb_wr_te(session: Session):
    _seed_two_teams(session)
    teams = compute_power_rankings(session, league_id=LEAGUE_ID)
    team_b = next(t for t in teams if t.team_name == "Team B")

    flex_slot = next(s for s in team_b.starters if s.slot == "FLEX")
    # Team B's best remaining skill player after 2 RB + 3 WR + 1 TE starters is Elite RB3.
    assert flex_slot.name == "Elite RB3"
    assert flex_slot.position == "RB"


def test_missing_league_raises() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        with pytest.raises(RuntimeError, match="sync"):
            compute_power_rankings(s, league_id="nope")


def test_no_rosters_raises(session: Session) -> None:
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=0, roster_positions=[]))
    session.commit()
    with pytest.raises(RuntimeError, match="No cached rosters"):
        compute_power_rankings(session, league_id=LEAGUE_ID)


def test_out_qb_is_skipped_for_starting_lineup_but_still_counts_in_positional_value(session: Session):
    _seed_two_teams(session)
    qb1 = session.query(PlayerRecord).filter_by(player_id="a_qb1").one()
    qb1.injury_status = "Out"
    qb1.injury_body_part = "Hamstring"
    session.commit()

    teams = compute_power_rankings(session, league_id=LEAGUE_ID)
    team_a = next(t for t in teams if t.team_name == "Team A")

    # Elite QB1 (rank 1, but Out) is skipped entirely -- Elite QB2 (rank 5,
    # healthy) fills the QB slot instead, and nothing puts QB1 in SUPER_FLEX either.
    qb_slot = next(s for s in team_a.starters if s.slot == "QB")
    assert qb_slot.name == "Elite QB2"
    assert qb_slot.injury_status is None
    assert all(s.player_id != "a_qb1" for s in team_a.starters)

    # But it still counts toward whole-roster QB positional value -- an
    # injured star still has value, they're just not starting right now.
    qb2 = session.query(PlayerRecord).filter_by(player_id="a_qb2").one()
    expected_qb_value = adjusted_player_value(1, qb1).value + adjusted_player_value(5, qb2).value
    assert team_a.positional_value["QB"] == pytest.approx(expected_qb_value)

    # And it's surfaced in the team's injured-players summary.
    injured = {p.player_id: p for p in team_a.injured_players}
    assert "a_qb1" in injured
    assert injured["a_qb1"].injury_status == "Out"
    assert injured["a_qb1"].multiplier == 0.75
