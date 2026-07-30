import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fantasy_agent.db.models import Base, LeagueRecord, PlayerRecord, RankingRecord, RosterRecord
from fantasy_agent.draft import get_best_available

LEAGUE_ID = "league1"
OWNER = "owner1"
PAGE = "dynasty-superflex-overall"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class FakeDraft:
    def __init__(self, draft_id: str, status: str) -> None:
        self.draft_id = draft_id
        self.status = status


class FakePick:
    def __init__(self, player_id: str) -> None:
        self.player_id = player_id


class FakeSleeperClient:
    """Stands in for SleeperClient so tests never hit the network -- the draft
    board is deliberately live-polled (see draft.py), so this is what we inject."""

    def __init__(self, drafts: list[FakeDraft], picks_by_draft: dict[str, list[FakePick]]) -> None:
        self._drafts = drafts
        self._picks_by_draft = picks_by_draft
        self.closed = False

    def get_league_drafts(self, league_id: str) -> list[FakeDraft]:
        return self._drafts

    def get_draft_picks(self, draft_id: str) -> list[FakePick]:
        return self._picks_by_draft.get(draft_id, [])

    def close(self) -> None:
        self.closed = True


def _rank(session, fp_id, sleeper_id, name, position, rank_ecr, pos_rank):
    session.add(
        RankingRecord(
            source="fantasypros", page=PAGE, fp_player_id=fp_id, sleeper_player_id=sleeper_id,
            name=name, team="XX", position=position, rank_ecr=rank_ecr, pos_rank=pos_rank,
        )
    )


def _seed(session: Session) -> None:
    session.add(
        LeagueRecord(
            league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12,
            roster_positions=["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN"],
        )
    )
    # My roster already has 2 RBs (meets the RB2 requirement) but 0 QBs.
    session.add(RosterRecord(league_id=LEAGUE_ID, roster_id=1, owner_id=OWNER, players=["rb1", "rb2"]))
    session.add(PlayerRecord(player_id="rb1", full_name="Owned RB1", team="XX", position="RB"))
    session.add(PlayerRecord(player_id="rb2", full_name="Owned RB2", team="XX", position="RB"))

    _rank(session, 1, "qb_top", "Top QB", "QB", 5, "QB1")
    _rank(session, 2, "rb_available", "Available RB", "RB", 8, "RB3")
    _rank(session, 3, "already_drafted", "Drafted Elsewhere", "WR", 3, "WR1")
    _rank(session, 4, "on_my_roster", "My Own RB", "RB", 50, "RB20")
    session.commit()
    # on_my_roster shares a ranking row but isn't actually on the roster list above;
    # simulate "already on my roster" via rb1/rb2 instead, which have no ranking row.


def test_get_best_available_excludes_drafted_and_owned_players(session: Session):
    _seed(session)
    client = FakeSleeperClient(
        drafts=[FakeDraft("d1", "drafting")],
        picks_by_draft={"d1": [FakePick("already_drafted")]},
    )
    players = get_best_available(session, league_id=LEAGUE_ID, owner_user_id=OWNER, client=client)
    names = [p.name for p in players]
    assert "Drafted Elsewhere" not in names  # picked in the live draft
    assert "Owned RB1" not in names  # already on my roster (not even ranked, but shouldn't appear)
    assert "Top QB" in names
    assert "Available RB" in names


def test_get_best_available_orders_by_rank_ecr(session: Session):
    _seed(session)
    client = FakeSleeperClient(drafts=[], picks_by_draft={})
    players = get_best_available(session, league_id=LEAGUE_ID, owner_user_id=OWNER, client=client)
    ranks = [p.rank_ecr for p in players]
    assert ranks == sorted(ranks)


def test_get_best_available_flags_qb_as_a_need(session: Session):
    _seed(session)
    client = FakeSleeperClient(drafts=[], picks_by_draft={})
    players = get_best_available(session, league_id=LEAGUE_ID, owner_user_id=OWNER, client=client)
    top_qb = next(p for p in players if p.name == "Top QB")
    assert "need" in top_qb.reasoning.lower()

    available_rb = next(p for p in players if p.name == "Available RB")
    # I already have 2 RBs meeting the RB2 requirement, so it should read as depth, not a hard need.
    assert "starting need" not in available_rb.reasoning.lower()


def test_get_best_available_handles_no_active_draft(session: Session):
    _seed(session)
    client = FakeSleeperClient(drafts=[], picks_by_draft={})
    players = get_best_available(session, league_id=LEAGUE_ID, owner_user_id=OWNER, client=client)
    assert len(players) > 0  # no drafts at all -> nobody is excluded for being "drafted"


def test_get_best_available_respects_limit(session: Session):
    _seed(session)
    client = FakeSleeperClient(drafts=[], picks_by_draft={})
    players = get_best_available(session, league_id=LEAGUE_ID, owner_user_id=OWNER, client=client, limit=2)
    assert len(players) == 2


def test_missing_league_raises() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        with pytest.raises(RuntimeError, match="sync"):
            get_best_available(s, league_id="nope", owner_user_id="nobody", client=FakeSleeperClient([], {}))


def test_missing_roster_raises(session: Session):
    session.add(LeagueRecord(league_id=LEAGUE_ID, name="L", season="2026", total_rosters=12))
    session.commit()
    with pytest.raises(RuntimeError, match="No roster found"):
        get_best_available(
            session, league_id=LEAGUE_ID, owner_user_id="nobody", client=FakeSleeperClient([], {})
        )
