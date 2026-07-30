"""League power rankings -- pure data pipeline, no LLM.

Ranks every roster 1..N two ways, both from live FantasyPros rankings:

1. Overall: value of each team's best possible *starting* lineup (not total
   roster value, which would just reward bench-hoarding). Filling FLEX/
   SUPER_FLEX is a greedy assignment (exact-position slots first, using each
   position's best remaining player, then FLEX from remaining RB/WR/TE, then
   SUPER_FLEX from remaining QB/RB/WR/TE) rather than a true optimal-assignment
   solver -- good enough in practice, and easy to explain.
2. Positional: for QB/RB/WR/TE, each team's *whole-roster* value at that
   position (not just starters) ranked against the other teams, to surface
   depth/strength by position rather than just who's in the lineup today.

Both use the same rank-to-value curve as the trade analyzer
(`trade.player_value`), so power rankings and trade-value numbers stay on
one consistent scale across the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .config import settings
from .db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from .roster_analysis import STANDARD_POSITIONS
from .trade import player_value

FLEX_ELIGIBLE = ("RB", "WR", "TE")
SUPER_FLEX_ELIGIBLE = ("QB", "RB", "WR", "TE")
EXACT_SLOT_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
NON_STARTER_SLOTS = ("BN", "IR", "TAXI")


@dataclass
class StarterSlot:
    slot: str
    player_id: str | None
    name: str | None
    position: str | None
    rank_ecr: int | None
    value: float


@dataclass
class TeamPowerRanking:
    rank: int
    team_name: str
    owner_user_id: str
    starting_lineup_value: float
    average_starter_rank: float | None
    starters: list[StarterSlot]
    positional_value: dict[str, float] = field(default_factory=dict)
    positional_rank: dict[str, int] = field(default_factory=dict)


def _fill_starting_lineup(
    roster_positions: list[str],
    roster_player_ids: list[str],
    players_by_id: dict[str, PlayerRecord],
    rank_by_player: dict[str, RankingRecord],
) -> list[StarterSlot]:
    remaining = list(roster_player_ids)

    def value_of(pid: str) -> float:
        ranking = rank_by_player.get(pid)
        return player_value(ranking.rank_ecr if ranking else None)

    def position_of(pid: str) -> str | None:
        player = players_by_id.get(pid)
        return player.position if player else None

    def best_for(exact: str | None, eligible: tuple[str, ...] | None) -> str | None:
        if exact is not None:
            candidates = [pid for pid in remaining if position_of(pid) == exact]
        else:
            candidates = [pid for pid in remaining if position_of(pid) in eligible]
        return max(candidates, key=value_of) if candidates else None

    starter_slots = [s for s in roster_positions if s not in NON_STARTER_SLOTS]
    ordered = (
        [s for s in starter_slots if s in EXACT_SLOT_POSITIONS]
        + [s for s in starter_slots if s == "FLEX"]
        + [s for s in starter_slots if s == "SUPER_FLEX"]
    )

    results: list[StarterSlot] = []
    for slot in ordered:
        if slot in EXACT_SLOT_POSITIONS:
            pid = best_for(slot, None)
        elif slot == "FLEX":
            pid = best_for(None, FLEX_ELIGIBLE)
        elif slot == "SUPER_FLEX":
            pid = best_for(None, SUPER_FLEX_ELIGIBLE)
        else:
            continue  # league uses a slot type (e.g. IDP) this app doesn't model

        if pid is None:
            results.append(
                StarterSlot(slot=slot, player_id=None, name=None, position=None, rank_ecr=None, value=0.0)
            )
            continue

        remaining.remove(pid)
        player = players_by_id.get(pid)
        ranking = rank_by_player.get(pid)
        results.append(
            StarterSlot(
                slot=slot,
                player_id=pid,
                name=(player.full_name if player else None) or pid,
                position=position_of(pid),
                rank_ecr=ranking.rank_ecr if ranking else None,
                value=value_of(pid),
            )
        )
    return results


def _positional_value(
    roster_player_ids: list[str],
    players_by_id: dict[str, PlayerRecord],
    rank_by_player: dict[str, RankingRecord],
) -> dict[str, float]:
    totals = {pos: 0.0 for pos in STANDARD_POSITIONS}
    for pid in roster_player_ids:
        player = players_by_id.get(pid)
        if player is None or player.position not in totals:
            continue
        ranking = rank_by_player.get(pid)
        totals[player.position] += player_value(ranking.rank_ecr if ranking else None)
    return totals


def compute_power_rankings(
    session: Session,
    *,
    league_id: str | None = None,
    rankings_page: str | None = None,
) -> list[TeamPowerRanking]:
    league_id = league_id or settings.sleeper_league_id
    rankings_page = rankings_page or settings.fantasypros_ranking_page

    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data -- run `fantasy-agent sync` first.")

    rosters = session.query(RosterRecord).filter_by(league_id=league_id).all()
    if not rosters:
        raise RuntimeError(f"No cached rosters for league {league_id} -- run `fantasy-agent sync` first.")

    users_by_id = {u.user_id: u for u in session.query(UserRecord).filter_by(league_id=league_id).all()}

    all_player_ids = {pid for r in rosters for pid in r.players}
    players_by_id = {
        p.player_id: p
        for p in session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(all_player_ids)).all()
    }
    rank_by_player = {
        r.sleeper_player_id: r
        for r in session.query(RankingRecord)
        .filter_by(source="fantasypros", page=rankings_page)
        .filter(RankingRecord.sleeper_player_id.in_(all_player_ids))
        .all()
        if r.sleeper_player_id
    }

    teams: list[TeamPowerRanking] = []
    for roster in rosters:
        owner = users_by_id.get(roster.owner_id)
        team_name = owner.team_name if owner else (roster.owner_id or f"Roster {roster.roster_id}")

        starters = _fill_starting_lineup(league.roster_positions, roster.players, players_by_id, rank_by_player)
        filled = [s for s in starters if s.rank_ecr is not None]
        total_value = sum(s.value for s in starters)
        avg_rank = sum(s.rank_ecr for s in filled) / len(filled) if filled else None

        teams.append(
            TeamPowerRanking(
                rank=0,  # filled in below, after sorting
                team_name=team_name,
                owner_user_id=roster.owner_id or "",
                starting_lineup_value=total_value,
                average_starter_rank=avg_rank,
                starters=starters,
                positional_value=_positional_value(roster.players, players_by_id, rank_by_player),
            )
        )

    teams.sort(key=lambda t: t.starting_lineup_value, reverse=True)
    for i, team in enumerate(teams, start=1):
        team.rank = i

    for position in STANDARD_POSITIONS:
        by_position = sorted(teams, key=lambda t: t.positional_value.get(position, 0.0), reverse=True)
        for i, team in enumerate(by_position, start=1):
            team.positional_rank[position] = i

    return teams
