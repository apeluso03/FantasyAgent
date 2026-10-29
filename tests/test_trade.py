import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from fantasy_agent.trade import adjusted_player_value, evaluate_trade, player_value

LEAGUE_ID = "league1"
OWNER_A = "ownerA"
OWNER_B = "ownerB"
PAGE = "dynasty-superflex"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _rank(session, fp_id, sleeper_id, name, position, rank_ecr, pos_rank):
    session.add(
        RankingRecord(
            source="fantasypros", page=PAGE, fp_player_id=fp_id, sleeper_player_id=sleeper_id,
            name=name, team="XX", position=position, rank_ecr=rank_ecr, pos_rank=pos_rank,
        )
    )


def _seed_even_trade(session: Session) -> None:
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12,
                              roster_positions=["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "BN", "BN"]))
    session.add(UserRecord(user_id=OWNER_A, league_id=LEAGUE_ID, display_name="A", team_name="Team A"))
    session.add(UserRecord(user_id=OWNER_B, league_id=LEAGUE_ID, display_name="B", team_name="Team B"))

    # Team A roster: has 3 WRs (surplus vs 3 needed... exactly at requirement), 1 RB (below the 2 needed)
    session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER_A,
                              players=["wr_a1", "wr_a2", "wr_a3", "rb_a1", "qb_trade"]))
    # Team B roster: has 1 WR, 3 RBs (surplus vs 2 needed)
    session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=2, owner_id=OWNER_B,
                              players=["wr_b1", "rb_b1", "rb_b2", "rb_trade"]))

    for pid, name, pos in [
        ("wr_a1", "WR A1", "WR"), ("wr_a2", "WR A2", "WR"), ("wr_a3", "WR A3", "WR"), ("rb_a1", "RB A1", "RB"),
        ("wr_b1", "WR B1", "WR"), ("rb_b1", "RB B1", "RB"), ("rb_b2", "RB B2", "RB"),
        ("qb_trade", "Traded QB", "QB"), ("rb_trade", "Traded RB", "RB"),
    ]:
        session.add(PlayerRecord(player_id=pid, full_name=name, team="XX", position=pos))

    # Same rank (same value) for the two traded pieces -> should be a "fair" verdict.
    _rank(session, 1, "qb_trade", "Traded QB", "QB", 50, "QB10")
    _rank(session, 2, "rb_trade", "Traded RB", "RB", 50, "RB10")
    session.commit()


def test_player_value_is_monotonic_decreasing():
    assert player_value(1) > player_value(50) > player_value(200)
    assert player_value(None) == 0.0


def test_even_value_trade_is_called_roughly_fair(session: Session):
    _seed_even_trade(session)
    result = evaluate_trade(session, OWNER_A, ["qb_trade"], OWNER_B, ["rb_trade"], league_id=LEAGUE_ID)
    assert "fair" in result.verdict.lower()
    assert result.side_a.value_given == result.side_b.value_received
    assert result.side_a.net_value == 0


def test_lopsided_trade_favors_the_side_receiving_more_value(session: Session):
    _seed_even_trade(session)
    # Add a second, much better player to side B's offer so it heavily favors A.
    session.add(PlayerRecord(player_id="stud", full_name="Stud Player", team="XX", position="WR"))
    _rank(session, 3, "stud", "Stud Player", "WR", 2, "WR1")
    session.query(RosterRecord).filter_by(owner_id=OWNER_B).one().players.append("stud")
    # SQLAlchemy JSON columns need reassignment to register the mutation.
    roster_b = session.query(RosterRecord).filter_by(owner_id=OWNER_B).one()
    roster_b.players = roster_b.players + ["stud"]
    session.commit()

    result = evaluate_trade(session, OWNER_A, ["qb_trade"], OWNER_B, ["rb_trade", "stud"], league_id=LEAGUE_ID)
    assert result.side_a.net_value > 0
    assert "Team A" in result.verdict
    assert "favors" in result.verdict.lower()


def test_roster_need_note_flags_position_dropping_below_requirement(session: Session):
    _seed_even_trade(session)
    result = evaluate_trade(session, OWNER_A, ["rb_a1"], OWNER_B, ["wr_b1"], league_id=LEAGUE_ID)
    # Team A trades away its only RB for a WR it already has 3 of.
    assert "creates a need" in result.side_a.reasoning
    assert result.side_a.position_counts_after["RB"] == 0


def test_trading_player_you_dont_own_raises(session: Session):
    _seed_even_trade(session)
    with pytest.raises(ValueError, match="doesn't own"):
        evaluate_trade(session, OWNER_A, ["rb_trade"], OWNER_B, ["wr_b1"], league_id=LEAGUE_ID)


def test_unknown_owner_raises(session: Session):
    _seed_even_trade(session)
    with pytest.raises(RuntimeError, match="No roster found"):
        evaluate_trade(session, "nobody", [], OWNER_B, [], league_id=LEAGUE_ID)


# --- adjusted_player_value -------------------------------------------------


def test_adjusted_player_value_healthy_player_matches_base_value():
    player = PlayerRecord(player_id="p1", injury_status=None)
    result = adjusted_player_value(50, player)
    assert result.value == player_value(50)
    assert result.multiplier == 1.0
    assert result.injury_status is None
    assert result.reason == ""


def test_adjusted_player_value_no_player_record():
    result = adjusted_player_value(50, None)
    assert result.value == player_value(50)
    assert result.multiplier == 1.0
    assert result.injury_status is None


def test_adjusted_player_value_unranked_player_is_still_zero():
    player = PlayerRecord(player_id="p1", injury_status="Out")
    result = adjusted_player_value(None, player)
    assert result.value == 0.0  # player_value(None) is 0 -- 0 times any multiplier is still 0
    assert result.multiplier == 0.75
    assert result.injury_status == "Out"


@pytest.mark.parametrize(
    "status, expected_multiplier",
    [
        ("Questionable", 0.95),
        ("Doubtful", 0.85),
        ("Out", 0.75),
        ("IR", 0.5),
        ("PUP", 0.5),
        ("Sus", 0.5),
    ],
)
def test_adjusted_player_value_applies_configured_multiplier(status, expected_multiplier):
    player = PlayerRecord(player_id="p1", injury_status=status, injury_body_part="Hamstring")
    result = adjusted_player_value(50, player)
    assert result.multiplier == expected_multiplier
    assert result.value == round(player_value(50) * expected_multiplier, 1)
    assert result.injury_status == status
    assert status in result.reason
    assert "Hamstring" in result.reason


def test_adjusted_player_value_empty_string_status_treated_as_healthy():
    # Sleeper's own real data includes a literal "" injury_status for a
    # couple of players -- treat that the same as no status at all, not an
    # unknown value worth warning about.
    player = PlayerRecord(player_id="p1", injury_status="")
    result = adjusted_player_value(50, player)
    assert result.multiplier == 1.0
    assert result.injury_status is None
    assert result.reason == ""


def test_adjusted_player_value_unknown_status_defaults_to_1x_and_warns(caplog):
    # "NA" is real Sleeper data (seen on inactive/non-roster players) but has
    # no configured multiplier -- falls back to 1.0 rather than guessing.
    player = PlayerRecord(player_id="p1", injury_status="NA")
    with caplog.at_level(logging.WARNING, logger="fantasy_agent.trade"):
        result = adjusted_player_value(50, player)
    assert result.multiplier == 1.0
    assert result.value == player_value(50)
    assert result.injury_status == "NA"
    assert "NA" in result.reason
    assert any("No injury value multiplier configured" in r.message for r in caplog.records)


# --- Injury-adjusted trades --------------------------------------------------


def test_trade_with_injured_player_shows_adjusted_value_and_injury_fields(session: Session):
    _seed_even_trade(session)
    # Side A's traded QB is Out -- its value given (and B's value received)
    # should both reflect the 0.75x discount, not the raw rank-based value.
    qb = session.query(PlayerRecord).filter_by(player_id="qb_trade").one()
    qb.injury_status = "Out"
    qb.injury_body_part = "Hamstring"
    session.commit()

    result = evaluate_trade(session, OWNER_A, ["qb_trade"], OWNER_B, ["rb_trade"], league_id=LEAGUE_ID)

    expected_value = round(player_value(50) * 0.75, 1)
    assert result.side_a.value_given == expected_value
    assert result.side_b.value_received == expected_value

    assert len(result.side_a.injured_players_given) == 1
    note = result.side_a.injured_players_given[0]
    assert note.name == "Traded QB"
    assert note.injury_status == "Out"
    assert note.multiplier == 0.75
    assert note.reason == "Out (Hamstring): value x0.75"

    assert len(result.side_b.injured_players_received) == 1
    assert result.side_b.injured_players_received[0].name == "Traded QB"

    # And the human-readable reasoning mentions it too, not just the fields.
    assert "Injury-adjusted" in result.side_a.reasoning
    assert "Traded QB" in result.side_a.reasoning
