"""Draft-day assistant: live best-available suggestions, no LLM.

Unlike rankings/roster data, "who's been drafted" must always be current, so
this pulls the draft's picks live from Sleeper on every call instead of
reading a cache (contrast with sync.py, which deliberately caches things
that are safe to go stale for a few hours).

Superflex-awareness comes from the data source, not extra logic here: the
rankings cache is built from FantasyPros' *superflex* consensus page (see
rankings/fantasypros.py), so QBs are already valued the way a 2-QB/superflex
market values them — a QB12 sits far higher in rank_ecr than it would on a
standard 1-QB board. This module's own job is narrower: drop already-drafted
players and annotate each remaining one with how it fits your roster.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .config import settings
from .db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord
from .roster_analysis import STANDARD_POSITIONS, position_counts, starter_requirements
from .sleeper.client import SleeperClient

FLEX_ELIGIBLE = ("RB", "WR", "TE")
SUPER_FLEX_ELIGIBLE = ("QB", "RB", "WR", "TE")


@dataclass
class BestAvailablePlayer:
    player_id: str
    name: str
    position: str
    team: str | None
    rank_ecr: int
    pos_rank: str | None
    reasoning: str


def _slot_demand(roster_positions: list[str]) -> dict[str, float]:
    """Starter-slot draw per position, splitting FLEX/SUPER_FLEX fractionally
    across their eligible positions instead of attributing them to one."""
    demand = {pos: 0.0 for pos in STANDARD_POSITIONS}
    for slot in roster_positions:
        if slot in demand:
            demand[slot] += 1.0
        elif slot == "FLEX":
            for pos in FLEX_ELIGIBLE:
                demand[pos] += 1.0 / len(FLEX_ELIGIBLE)
        elif slot == "SUPER_FLEX":
            for pos in SUPER_FLEX_ELIGIBLE:
                demand[pos] += 1.0 / len(SUPER_FLEX_ELIGIBLE)
    return demand


def _find_current_draft_id(client: SleeperClient, league_id: str) -> str | None:
    drafts = client.get_league_drafts(league_id)
    if not drafts:
        return None
    # Prefer a draft that's actually pending/in-progress over a stale complete
    # one from a prior season sharing this league_id chain.
    active = [d for d in drafts if d.status in ("pre_draft", "drafting")]
    pool = active or drafts
    return max(pool, key=lambda d: d.draft_id).draft_id


def _need_note(position: str | None, have: int, need: float, req: int) -> str:
    if position is None:
        return ""
    if have < req:
        plural = "s" if req != 1 else ""
        return f"You have {have} {position}{'s' if have != 1 else ''} and need at least {req} starter{plural} — fills a starting need."
    if have < round(need):
        return f"You have {have} {position}s; roughly {need:.1f} starter slots (incl. FLEX/SUPER_FLEX) draw on {position} — still useful depth."
    return f"You already have {have} {position}s, likely bench depth from here."


def get_best_available(
    session: Session,
    *,
    league_id: str | None = None,
    owner_user_id: str | None = None,
    rankings_page: str | None = None,
    limit: int = 15,
    client: SleeperClient | None = None,
) -> list[BestAvailablePlayer]:
    league_id = league_id or settings.sleeper_league_id
    owner_user_id = owner_user_id or settings.sleeper_owner_user_id
    rankings_page = rankings_page or settings.fantasypros_ranking_page

    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data — run `fantasy-agent sync` first.")

    roster = (
        session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner_user_id).one_or_none()
    )
    if roster is None:
        raise RuntimeError(f"No roster found for owner_id={owner_user_id} in league {league_id}.")

    owns_client = client is None
    client = client or SleeperClient(base_url=settings.sleeper_base_url)
    try:
        draft_id = _find_current_draft_id(client, league_id)
        drafted_ids: set[str] = set()
        if draft_id is not None:
            drafted_ids = {p.player_id for p in client.get_draft_picks(draft_id)}
    finally:
        if owns_client:
            client.close()

    rankings = (
        session.query(RankingRecord)
        .filter_by(source="fantasypros", page=rankings_page)
        .filter(RankingRecord.sleeper_player_id.isnot(None))
        .order_by(RankingRecord.rank_ecr)
        .all()
    )

    players_by_id = {
        p.player_id: p
        for p in session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(roster.players)).all()
    }
    my_counts = position_counts(roster.players, players_by_id)
    requirements = starter_requirements(league.roster_positions)
    demand = _slot_demand(league.roster_positions)

    unavailable = drafted_ids | set(roster.players)
    available: list[BestAvailablePlayer] = []
    for r in rankings:
        if r.sleeper_player_id in unavailable:
            continue
        if len(available) >= limit:
            break

        pos = r.position if r.position in STANDARD_POSITIONS else None
        have = my_counts.get(pos, 0) if pos else 0
        need = demand.get(pos, 0.0) if pos else 0.0
        req = requirements.get(pos, 0) if pos else 0
        reasoning = f"Ranked #{r.rank_ecr} overall ({r.pos_rank}). {_need_note(pos, have, need, req)}".strip()

        available.append(
            BestAvailablePlayer(
                player_id=r.sleeper_player_id,
                name=r.name,
                position=r.position,
                team=r.team,
                rank_ecr=r.rank_ecr,
                pos_rank=r.pos_rank,
                reasoning=reasoning,
            )
        )

    return available
