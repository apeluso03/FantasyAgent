"""Full-roster view for a single team (the user edition's "My Roster" tab).

Unlike power_rankings.TeamPowerRanking, which recomputes the *optimal*
starting lineup for cross-team comparison, this reflects the lineup the
owner has actually set in Sleeper (RosterRecord.starters/reserve/taxi) --
what you'd want to see when just looking at your own team.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .config import settings
from .db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord

# Sleeper pads the starters array with "0" for empty slots rather than omitting them.
_EMPTY_SLOT = "0"
_NON_STARTER_SLOTS = ("BN", "IR", "TAXI")

# Real-roster display order for starters, top to bottom -- not draft/ranking order.
# Anything not listed here (a slot type this app doesn't otherwise model, e.g. IDP)
# sorts after these but still before bench.
_STARTER_SLOT_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]


def _slot_sort_key(slot: str) -> int:
    try:
        return _STARTER_SLOT_ORDER.index(slot)
    except ValueError:
        return len(_STARTER_SLOT_ORDER)


@dataclass
class RosterPlayer:
    player_id: str
    name: str
    position: str | None
    team: str | None
    rank_ecr: int | None
    pos_rank: str | None
    group: str  # "starter", "bench", "ir", or "taxi"
    slot: str | None = None  # the starting slot this player fills (e.g. "FLEX"); None off the bench


@dataclass
class MyRoster:
    team_name: str
    owner_user_id: str
    players: list[RosterPlayer]


def get_my_roster(
    session: Session,
    *,
    league_id: str | None = None,
    owner_user_id: str | None = None,
    rankings_page: str | None = None,
) -> MyRoster:
    league_id = league_id or settings.sleeper_league_id
    owner_user_id = owner_user_id or settings.sleeper_owner_user_id
    rankings_page = rankings_page or settings.fantasypros_ranking_page

    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data -- run a sync first.")

    roster = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner_user_id).one_or_none()
    if roster is None:
        raise RuntimeError(f"No roster found for owner_id={owner_user_id} in league {league_id}.")

    user = session.query(UserRecord).filter_by(league_id=league_id, user_id=owner_user_id).one_or_none()
    team_name = (user.team_name if user else None) or owner_user_id or f"Roster {roster.roster_id}"

    players_by_id = {
        p.player_id: p
        for p in session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(roster.players)).all()
    }
    rank_by_player = {
        r.sleeper_player_id: r
        for r in session.query(RankingRecord)
        .filter_by(source="fantasypros", page=rankings_page)
        .filter(RankingRecord.sleeper_player_id.in_(roster.players))
        .all()
        if r.sleeper_player_id
    }

    reserve_ids = set(roster.reserve)
    taxi_ids = set(roster.taxi)

    # Sleeper's `starters` array is positionally aligned with the starter
    # (non-BN/IR/TAXI) subset of the league's roster_positions, in order --
    # zipping the two recovers which specific slot (QB, FLEX, SUPER_FLEX, ...)
    # each starter fills, not just "is a starter."
    starter_slot_types = [s for s in league.roster_positions if s not in _NON_STARTER_SLOTS]
    slot_by_player: dict[str, str] = {
        pid: slot_type
        for slot_type, pid in zip(starter_slot_types, roster.starters)
        if pid != _EMPTY_SLOT
    }

    def group_of(pid: str) -> str:
        if pid in taxi_ids:
            return "taxi"
        if pid in reserve_ids:
            return "ir"
        if pid in slot_by_player:
            return "starter"
        return "bench"

    players: list[RosterPlayer] = []
    for pid in roster.players:
        player = players_by_id.get(pid)
        ranking = rank_by_player.get(pid)
        players.append(
            RosterPlayer(
                player_id=pid,
                name=(player.full_name if player else None) or pid,
                position=player.position if player else None,
                team=player.team if player else None,
                rank_ecr=ranking.rank_ecr if ranking else None,
                pos_rank=ranking.pos_rank if ranking else None,
                group=group_of(pid),
                slot=slot_by_player.get(pid),
            )
        )

    group_order = {"starter": 0, "bench": 1, "ir": 2, "taxi": 3}

    def sort_key(rp: RosterPlayer) -> tuple[int, int, int]:
        rank = rp.rank_ecr if rp.rank_ecr is not None else 9999
        if rp.group == "starter":
            return (group_order["starter"], _slot_sort_key(rp.slot or ""), rank)
        return (group_order.get(rp.group, 9), 0, rank)

    players.sort(key=sort_key)

    return MyRoster(team_name=team_name, owner_user_id=owner_user_id, players=players)
