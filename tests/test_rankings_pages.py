"""Rankings page selection (horizon x league format) and the derived
rest-of-season superflex page."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, RankingRecord
from fantasy_agent.rankings.pages import (
    DERIVED_ROS_SUPERFLEX,
    ROS_1QB,
    SOURCE_PAGES,
    WEEKLY_SUPERFLEX,
    derive_superflex_order,
    is_superflex,
    rankings_page,
)
from fantasy_agent.sync import derive_ros_superflex, get_last_synced


@pytest.mark.parametrize(
    "positions, expected",
    [
        (["QB", "RB", "WR", "SUPER_FLEX", "BN"], True),
        (["QB", "QB", "RB", "WR", "BN"], True),  # 2QB values QBs like superflex
        (["QB", "RB", "WR", "FLEX", "BN"], False),
    ],
)
def test_is_superflex(positions, expected):
    assert is_superflex(positions) is expected


def test_every_horizon_has_a_page_for_both_formats():
    assert rankings_page("ros", superflex=True) == DERIVED_ROS_SUPERFLEX
    assert rankings_page("ros", superflex=False) == ROS_1QB
    assert rankings_page("dynasty", superflex=True) != rankings_page("dynasty", superflex=False)
    # The derived page is built, never scraped.
    assert DERIVED_ROS_SUPERFLEX not in SOURCE_PAGES


def test_derive_moves_qbs_up_to_the_reference_spacing():
    # 1-QB ranking: QBs buried behind skill players.
    base = [("rb1", "RB"), ("wr1", "WR"), ("rb2", "RB"), ("qbA", "QB"), ("wr2", "WR"), ("qbB", "QB")]
    # Superflex reference: QB1 is the best player, QB2 comes after one skill player.
    reference = ["QB", "WR", "QB", "RB", "RB"]

    assert derive_superflex_order(base, reference) == ["qbA", "rb1", "qbB", "wr1", "rb2", "wr2"]


def test_derive_keeps_order_within_qbs_and_within_skill_players():
    base = [("wr1", "WR"), ("qb1", "QB"), ("rb1", "RB"), ("qb2", "QB"), ("te1", "TE"), ("qb3", "QB")]
    reference = ["QB", "QB", "WR", "QB", "RB"]
    order = derive_superflex_order(base, reference)

    assert [k for k in order if k.startswith("qb")] == ["qb1", "qb2", "qb3"]
    assert [k for k in order if not k.startswith("qb")] == ["wr1", "rb1", "te1"]


def test_derive_kickers_and_defenses_dont_count_as_skill_players():
    # K/DST never compete with a QB for a superflex spot, so they mustn't
    # shift where QBs land.
    base = [("k1", "K"), ("rb1", "RB"), ("qb1", "QB")]
    reference = ["RB", "QB"]  # QB1 comes after exactly one skill player
    assert derive_superflex_order(base, reference) == ["k1", "rb1", "qb1"]


def test_derive_extends_spacing_past_the_end_of_the_reference():
    base = [(f"s{i}", "WR") for i in range(10)] + [("qb1", "QB"), ("qb2", "QB"), ("qb3", "QB")]
    reference = ["QB", "WR", "WR", "QB"]  # QBs 2 skill players apart; no third QB
    order = derive_superflex_order(base, reference)

    assert order.index("qb1") == 0
    assert order.index("qb2") == 3  # after 2 skill players (+1 for qb1)
    assert order.index("qb3") == 6  # extrapolated: 2 more skill players later


def test_derive_with_no_reference_qbs_leaves_qbs_at_the_end():
    base = [("qb1", "QB"), ("rb1", "RB")]
    assert derive_superflex_order(base, ["RB", "WR"]) == ["rb1", "qb1"]


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _rank(session, page, fp_id, name, position, rank, pos_rank=None, sleeper_id=None):
    session.add(RankingRecord(source="fantasypros", page=page, fp_player_id=fp_id, sleeper_player_id=sleeper_id,
                               name=name, position=position, rank_ecr=rank, pos_rank=pos_rank,
                               match_method="exact" if sleeper_id else "unmatched"))


def test_derive_ros_superflex_writes_a_reranked_page(session: Session):
    _rank(session, ROS_1QB, 1, "Bijan Robinson", "RB", 1, "RB1", "s1")
    _rank(session, ROS_1QB, 2, "Ja'Marr Chase", "WR", 2, "WR1", "s2")
    _rank(session, ROS_1QB, 3, "Josh Allen", "QB", 3, "QB1", "s3")
    _rank(session, WEEKLY_SUPERFLEX, 10, "Josh Allen", "QB", 1)
    _rank(session, WEEKLY_SUPERFLEX, 11, "Bijan Robinson", "RB", 2)
    session.commit()

    result = derive_ros_superflex(session)
    session.commit()

    rows = (
        session.query(RankingRecord).filter_by(page=DERIVED_ROS_SUPERFLEX).order_by(RankingRecord.rank_ecr).all()
    )
    assert [(r.name, r.rank_ecr, r.pos_rank, r.sleeper_player_id) for r in rows] == [
        ("Josh Allen", 1, "QB1", "s3"),
        ("Bijan Robinson", 2, "RB1", "s1"),
        ("Ja'Marr Chase", 3, "WR1", "s2"),
    ]
    assert result.total == 3
    assert get_last_synced(session, f"rankings:{DERIVED_ROS_SUPERFLEX}") is not None


def test_derive_ros_superflex_replaces_the_previous_derivation(session: Session):
    _rank(session, ROS_1QB, 1, "Bijan Robinson", "RB", 1, "RB1", "s1")
    _rank(session, WEEKLY_SUPERFLEX, 11, "Bijan Robinson", "RB", 1)
    session.commit()
    derive_ros_superflex(session)
    derive_ros_superflex(session)
    session.commit()
    assert session.query(RankingRecord).filter_by(page=DERIVED_ROS_SUPERFLEX).count() == 1


def test_derive_ros_superflex_skips_without_both_sources(session: Session):
    _rank(session, ROS_1QB, 1, "Bijan Robinson", "RB", 1)
    session.commit()
    assert derive_ros_superflex(session) is None
    assert session.query(RankingRecord).filter_by(page=DERIVED_ROS_SUPERFLEX).count() == 0
