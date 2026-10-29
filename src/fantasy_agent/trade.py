"""Trade analyzer — pure data pipeline, no LLM.

Evaluates a proposed trade for both sides on two axes:

1. Value: each player's rank_ecr is converted to a value score via a simple
   exponential decay curve (`player_value`) — not a precise valuation model,
   just a monotonic, explainable stand-in so "value given" and "value
   received" are comparable numbers, similar in spirit to public dynasty
   trade-value charts. `adjusted_player_value()` layers a modest injury
   discount on top of that same curve (see its own docstring) — this lives
   here, not a separate module, so power_rankings.py's existing
   `from .trade import player_value` covers it too without a new import path
   or any risk of a circular import.
2. Roster context: does the trade fill a positional need or create a
   surplus for each side, based on simple pre/post position counts against
   the league's starter requirements (QB/RB/WR/TE slot counts from
   roster_positions — FLEX/SUPER_FLEX aren't attributed to a single
   position, so this is a simplification, not exact need accounting).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .config import settings
from .db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from .roster_analysis import STANDARD_POSITIONS, position_counts, starter_requirements

logger = logging.getLogger(__name__)


def player_value(rank_ecr: int | None) -> float:
    """Monotonic decay curve turning an ECR rank into a comparable value score.
    Unranked players (no FantasyPros match) are treated as zero value."""
    if rank_ecr is None or rank_ecr < 1:
        return 0.0
    return round(1000 * (0.99 ** (rank_ecr - 1)), 1)


@dataclass
class AdjustedValue:
    value: float
    multiplier: float
    injury_status: str | None
    reason: str  # e.g. "Out (hamstring): value x0.75" -- "" when there's nothing to explain


@dataclass
class InjuryNote:
    """One injured/flagged player involved in a trade or a roster, for
    display alongside the plain value numbers (TradeSideResult,
    TeamPowerRanking in power_rankings.py)."""

    player_id: str
    name: str
    injury_status: str
    multiplier: float
    reason: str


def adjusted_player_value(rank_ecr: int | None, player: PlayerRecord | None) -> AdjustedValue:
    """`player_value()` with a modest, explainable injury discount layered on
    top, via Settings.injury_value_multipliers.

    Deliberately just a flat multiplier, not an injury-risk model: this is a
    keeper league, and FantasyPros' own rankings already partly price in
    injuries (a hobbled player usually slides in ECR on its own), so this is
    meant as a small, legible nudge on top of that -- not a second, competing
    valuation system. A status with no configured multiplier (anything
    outside Settings.injury_value_multipliers, e.g. Sleeper's "NA" or rarer
    ones like "COV"/"DNR") defaults to 1.0 (no adjustment) and logs a
    warning, rather than guessing at a discount.
    """
    base = player_value(rank_ecr)
    status = (player.injury_status if player else None) or None  # "" normalizes to None, same as no status
    if not status:
        return AdjustedValue(value=base, multiplier=1.0, injury_status=None, reason="")

    multiplier = settings.injury_value_multipliers.get(status.lower())
    if multiplier is None:
        logger.warning(
            "No injury value multiplier configured for status %r -- defaulting to 1.0 "
            "(add it to Settings.injury_value_multipliers if it should discount value)",
            status,
        )
        multiplier = 1.0

    adjusted = round(base * multiplier, 1)
    body_part = f" ({player.injury_body_part})" if player and player.injury_body_part else ""
    reason = f"{status}{body_part}: value x{multiplier:g}"
    return AdjustedValue(value=adjusted, multiplier=multiplier, injury_status=status, reason=reason)


def _injury_notes(
    player_ids: list[str],
    players_by_id: dict[str, PlayerRecord],
    adjustments: dict[str, AdjustedValue],
) -> list[InjuryNote]:
    notes = []
    for pid in player_ids:
        adj = adjustments[pid]
        if not adj.injury_status:
            continue
        player = players_by_id.get(pid)
        name = (player.full_name if player else None) or pid
        notes.append(
            InjuryNote(
                player_id=pid, name=name, injury_status=adj.injury_status, multiplier=adj.multiplier, reason=adj.reason
            )
        )
    return notes


def _injury_reasoning_note(injured_given: list[InjuryNote], injured_received: list[InjuryNote]) -> str:
    bits = [f"{n.name}: {n.reason}" for n in (*injured_given, *injured_received)]
    return f" Injury-adjusted: {'; '.join(bits)}." if bits else ""


@dataclass
class TradeSideResult:
    owner_user_id: str
    team_name: str
    gives: list[str]
    receives: list[str]
    value_given: float
    value_received: float
    net_value: float
    position_counts_before: dict[str, int]
    position_counts_after: dict[str, int]
    reasoning: str
    # Structured injury detail for display -- value_given/value_received
    # above already have these discounts baked in; this is so a caller can
    # show exactly which players were adjusted and why.
    injured_players_given: list[InjuryNote] = field(default_factory=list)
    injured_players_received: list[InjuryNote] = field(default_factory=list)


@dataclass
class TradeEvaluation:
    side_a: TradeSideResult
    side_b: TradeSideResult
    verdict: str


def _player_label(pid: str, players_by_id: dict[str, PlayerRecord], rank_by_id: dict[str, RankingRecord]) -> str:
    player = players_by_id.get(pid)
    name = (player.full_name if player else None) or pid
    ranking = rank_by_id.get(pid)
    rank_desc = f"#{ranking.rank_ecr} {ranking.pos_rank}" if ranking else "unranked"
    return f"{name} ({rank_desc})"


def _need_notes(before: dict[str, int], after: dict[str, int], requirements: dict[str, int]) -> list[str]:
    notes = []
    for pos in STANDARD_POSITIONS:
        b, a, req = before[pos], after[pos], requirements.get(pos, 0)
        if b == a:
            continue
        if a < req:
            notes.append(f"{pos} drops to {a} (below your {req} starter slot{'s' if req != 1 else ''}) — creates a need")
        elif a > b and b > req:
            notes.append(f"{pos} grows to {a} (already had {b} >= {req} needed) — adds to a surplus")
        else:
            notes.append(f"{pos} goes from {b} to {a}")
    return notes


def _build_side(
    owner_user_id: str,
    team_name: str,
    gives: list[str],
    receives: list[str],
    roster: RosterRecord,
    players_by_id: dict[str, PlayerRecord],
    rank_by_id: dict[str, RankingRecord],
    requirements: dict[str, int],
) -> TradeSideResult:
    given_adjustments = {
        p: adjusted_player_value(rank_by_id[p].rank_ecr if p in rank_by_id else None, players_by_id.get(p))
        for p in gives
    }
    received_adjustments = {
        p: adjusted_player_value(rank_by_id[p].rank_ecr if p in rank_by_id else None, players_by_id.get(p))
        for p in receives
    }
    value_given = sum(a.value for a in given_adjustments.values())
    value_received = sum(a.value for a in received_adjustments.values())

    injured_given = _injury_notes(gives, players_by_id, given_adjustments)
    injured_received = _injury_notes(receives, players_by_id, received_adjustments)

    before = position_counts(roster.players, players_by_id)
    after_players = [p for p in roster.players if p not in gives] + receives
    after = position_counts(after_players, players_by_id)

    gives_desc = ", ".join(_player_label(p, players_by_id, rank_by_id) for p in gives) or "nothing"
    receives_desc = ", ".join(_player_label(p, players_by_id, rank_by_id) for p in receives) or "nothing"
    need_notes = _need_notes(before, after, requirements)

    net = value_received - value_given
    value_desc = f"gives up {value_given:.0f} value, receives {value_received:.0f} value (net {net:+.0f})"
    reasoning = f"Sends: {gives_desc}. Receives: {receives_desc}. {value_desc}."
    if need_notes:
        reasoning += " Roster impact: " + "; ".join(need_notes) + "."
    reasoning += _injury_reasoning_note(injured_given, injured_received)

    return TradeSideResult(
        owner_user_id=owner_user_id,
        team_name=team_name,
        injured_players_given=injured_given,
        injured_players_received=injured_received,
        gives=gives,
        receives=receives,
        value_given=value_given,
        value_received=value_received,
        net_value=net,
        position_counts_before=before,
        position_counts_after=after,
        reasoning=reasoning,
    )


def evaluate_trade(
    session: Session,
    side_a_owner: str,
    side_a_gives: list[str],
    side_b_owner: str,
    side_b_gives: list[str],
    *,
    league_id: str | None = None,
    rankings_page: str | None = None,
) -> TradeEvaluation:
    league_id = league_id or settings.sleeper_league_id
    rankings_page = rankings_page or settings.fantasypros_ranking_page

    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data — run `fantasy-agent sync` first.")

    roster_a = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=side_a_owner).one_or_none()
    roster_b = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=side_b_owner).one_or_none()
    if roster_a is None:
        raise RuntimeError(f"No roster found for owner_id={side_a_owner} in league {league_id}.")
    if roster_b is None:
        raise RuntimeError(f"No roster found for owner_id={side_b_owner} in league {league_id}.")

    missing_a = [p for p in side_a_gives if p not in roster_a.players]
    missing_b = [p for p in side_b_gives if p not in roster_b.players]
    if missing_a:
        raise ValueError(f"Side A doesn't own: {', '.join(missing_a)}")
    if missing_b:
        raise ValueError(f"Side B doesn't own: {', '.join(missing_b)}")

    all_player_ids = set(side_a_gives) | set(side_b_gives)
    players_by_id = {
        p.player_id: p for p in session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(all_player_ids)).all()
    }
    rank_by_id = {
        r.sleeper_player_id: r
        for r in session.query(RankingRecord)
        .filter_by(source="fantasypros", page=rankings_page)
        .filter(RankingRecord.sleeper_player_id.in_(all_player_ids))
        .all()
        if r.sleeper_player_id
    }
    # Position-count context needs every rostered player looked up, not just traded ones.
    all_roster_players = set(roster_a.players) | set(roster_b.players)
    players_by_id.update(
        {
            p.player_id: p
            for p in session.query(PlayerRecord)
            .filter(PlayerRecord.player_id.in_(all_roster_players))
            .all()
            if p.player_id not in players_by_id
        }
    )

    requirements = starter_requirements(league.roster_positions)

    user_a = session.query(UserRecord).filter_by(league_id=league_id, user_id=side_a_owner).one_or_none()
    user_b = session.query(UserRecord).filter_by(league_id=league_id, user_id=side_b_owner).one_or_none()
    team_name_a = user_a.team_name if user_a else side_a_owner
    team_name_b = user_b.team_name if user_b else side_b_owner

    side_a = _build_side(
        side_a_owner, team_name_a, side_a_gives, side_b_gives, roster_a, players_by_id, rank_by_id, requirements
    )
    side_b = _build_side(
        side_b_owner, team_name_b, side_b_gives, side_a_gives, roster_b, players_by_id, rank_by_id, requirements
    )

    total_value = side_a.value_given + side_b.value_given
    if total_value == 0:
        verdict = "Can't assess by value — none of the traded players are in the rankings cache."
    else:
        pct_diff = abs(side_a.net_value) / total_value
        favored = side_a.team_name if side_a.net_value > 0 else side_b.team_name
        if pct_diff < 0.10:
            verdict = "Roughly fair value on both sides."
        elif pct_diff < 0.30:
            verdict = f"Moderately favors {favored} by value ({pct_diff:.0%} value gap)."
        else:
            verdict = f"Heavily favors {favored} by value ({pct_diff:.0%} value gap) — worth a second look."

    return TradeEvaluation(side_a=side_a, side_b=side_b, verdict=verdict)
