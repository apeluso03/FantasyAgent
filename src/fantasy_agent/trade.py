"""Trade analyzer — pure data pipeline, no LLM.

Evaluates a proposed trade for both sides on two axes:

1. Value: each player's rank_ecr is converted to a value score via a simple
   exponential decay curve (`player_value`) — not a precise valuation model,
   just a monotonic, explainable stand-in so "value given" and "value
   received" are comparable numbers, similar in spirit to public dynasty
   trade-value charts.
2. Roster context: does the trade fill a positional need or create a
   surplus for each side, based on simple pre/post position counts against
   the league's starter requirements (QB/RB/WR/TE slot counts from
   roster_positions — FLEX/SUPER_FLEX aren't attributed to a single
   position, so this is a simplification, not exact need accounting).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .config import settings
from .db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from .roster_analysis import STANDARD_POSITIONS, position_counts, starter_requirements


def player_value(rank_ecr: int | None) -> float:
    """Monotonic decay curve turning an ECR rank into a comparable value score.
    Unranked players (no FantasyPros match) are treated as zero value."""
    if rank_ecr is None or rank_ecr < 1:
        return 0.0
    return round(1000 * (0.99 ** (rank_ecr - 1)), 1)


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
    value_given = sum(player_value(rank_by_id[p].rank_ecr if p in rank_by_id else None) for p in gives)
    value_received = sum(player_value(rank_by_id[p].rank_ecr if p in rank_by_id else None) for p in receives)

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

    return TradeSideResult(
        owner_user_id=owner_user_id,
        team_name=team_name,
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

    user_a = session.get(UserRecord, side_a_owner)
    user_b = session.get(UserRecord, side_b_owner)
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
