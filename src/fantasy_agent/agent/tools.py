"""Tools exposed to the agent's tool-calling loop.

Each tool pairs a JSON schema (what Claude sees) with a handler that takes the
open DB session plus the tool's parsed input and returns a JSON-serializable
dict. Keeping tool outputs structured — not prose — lets the agent reason
over them directly rather than re-parsing text, per the spec's agent design
notes. Handlers read from the local cache, with one deliberate exception:
get_best_available polls Sleeper's draft endpoint live, since "who's been
picked" can't be allowed to go stale mid-draft (see draft.py).
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from ..draft import get_best_available as _get_best_available_pipeline
from ..keeper import compute_keeper_candidates
from ..rankings.matching import normalize_name
from ..trade import evaluate_trade as _evaluate_trade_pipeline


class ToolError(RuntimeError):
    """Raised by a tool handler; the message is sent back to Claude as a tool_result error."""


def _league_id() -> str:
    return settings.sleeper_league_id


def resolve_owner(session: Session, name_or_username: str) -> UserRecord:
    needle = name_or_username.strip().lower()
    users = session.query(UserRecord).filter_by(league_id=_league_id()).all()

    exact = [
        u for u in users
        if (u.team_name or "").lower() == needle or (u.display_name or "").lower() == needle
    ]
    if len(exact) == 1:
        return exact[0]

    candidates = [
        u for u in users
        if needle in (u.team_name or "").lower() or needle in (u.display_name or "").lower()
    ]
    if len(candidates) == 1:
        return candidates[0]

    all_names = ", ".join(u.team_name or u.display_name or u.user_id for u in users)
    if not candidates:
        raise ToolError(f"No team matches '{name_or_username}'. Teams in this league: {all_names}")
    matched = ", ".join(u.team_name or u.display_name or u.user_id for u in candidates)
    raise ToolError(f"'{name_or_username}' matches multiple teams ({matched}). Be more specific.")


def _resolve_players_on_roster(session: Session, roster: RosterRecord, names: list[str]) -> list[str]:
    players = session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(roster.players)).all()
    by_norm: dict[str, list[PlayerRecord]] = {}
    for p in players:
        if p.full_name:
            by_norm.setdefault(normalize_name(p.full_name), []).append(p)

    resolved: list[str] = []
    for name in names:
        norm = normalize_name(name)
        matches = by_norm.get(norm)
        if not matches:
            matches = [p for cand_norm, ps in by_norm.items() if norm in cand_norm for p in ps]
        if not matches:
            roster_names = ", ".join(p.full_name for p in players if p.full_name)
            raise ToolError(f"'{name}' is not on this roster. Roster: {roster_names}")
        if len(matches) > 1:
            options = ", ".join(f"{p.full_name} ({p.position})" for p in matches)
            raise ToolError(f"'{name}' matches multiple players on this roster ({options}). Be more specific.")
        resolved.append(matches[0].player_id)
    return resolved


def _tool_get_league_info(session: Session, **_: Any) -> dict:
    league = session.get(LeagueRecord, _league_id())
    if league is None:
        raise ToolError("No cached league data. Run `fantasy-agent sync` first.")
    return {
        "name": league.name,
        "season": league.season,
        "total_rosters": league.total_rosters,
        "roster_positions": league.roster_positions,
        "scoring_highlights": {
            k: v
            for k, v in league.scoring_settings.items()
            if k in ("rec", "pass_td", "rush_td", "rec_td", "pass_int", "fum_lost")
        },
        "keeper_settings": {
            "is_keeper_league": league.settings.get("type") == 1,
            "max_keepers": league.settings.get("max_keepers"),
        },
        "trade_deadline_week": league.settings.get("trade_deadline"),
    }


def _tool_list_rosters(session: Session, **_: Any) -> dict:
    league_id = _league_id()
    users_by_id = {u.user_id: u for u in session.query(UserRecord).filter_by(league_id=league_id).all()}
    rosters = (
        session.query(RosterRecord).filter_by(league_id=league_id).order_by(RosterRecord.roster_id).all()
    )
    all_player_ids = {pid for r in rosters for pid in r.players}
    players_by_id = {
        p.player_id: p
        for p in session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(all_player_ids)).all()
    }

    teams = []
    for r in rosters:
        owner = users_by_id.get(r.owner_id)
        position_counts: dict[str, int] = {}
        for pid in r.players:
            p = players_by_id.get(pid)
            if p and p.position:
                position_counts[p.position] = position_counts.get(p.position, 0) + 1
        teams.append(
            {
                "team_name": owner.team_name if owner else "(unowned)",
                "record": {"wins": r.settings.get("wins"), "losses": r.settings.get("losses")},
                "position_counts": position_counts,
                "roster_size": len(r.players),
            }
        )
    return {"teams": teams}


def _tool_search_player(session: Session, name: str, limit: int = 10, **_: Any) -> dict:
    needle = name.strip().lower()
    matches = [p for p in session.query(PlayerRecord).all() if p.full_name and needle in p.full_name.lower()][
        :limit
    ]
    return {
        "matches": [
            {"player_id": p.player_id, "name": p.full_name, "position": p.position, "team": p.team}
            for p in matches
        ]
    }


def _tool_get_roster(session: Session, team: str, **_: Any) -> dict:
    league_id = _league_id()
    owner = resolve_owner(session, team)
    roster = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner.user_id).one()
    players = session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(roster.players)).all()
    rankings = {
        r.sleeper_player_id: r
        for r in session.query(RankingRecord)
        .filter_by(source="fantasypros", page=settings.fantasypros_ranking_page)
        .filter(RankingRecord.sleeper_player_id.in_(roster.players))
        .all()
        if r.sleeper_player_id
    }
    return {
        "team_name": owner.team_name,
        "players": [
            {
                "player_id": p.player_id,
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "rank_ecr": rankings[p.player_id].rank_ecr if p.player_id in rankings else None,
                "pos_rank": rankings[p.player_id].pos_rank if p.player_id in rankings else None,
            }
            for p in players
        ],
    }


def _tool_get_rankings(
    session: Session,
    position: str | None = None,
    search: str | None = None,
    limit: int = 30,
    **_: Any,
) -> dict:
    rows = (
        session.query(RankingRecord)
        .filter_by(source="fantasypros", page=settings.fantasypros_ranking_page)
        .all()
    )
    if position:
        rows = [r for r in rows if r.position == position.upper()]
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in r.name.lower()]
    rows.sort(key=lambda r: r.rank_ecr)
    rows = rows[:limit]
    return {
        "rankings": [
            {
                "rank_ecr": r.rank_ecr,
                "name": r.name,
                "position": r.position,
                "team": r.team,
                "pos_rank": r.pos_rank,
                "sleeper_player_id": r.sleeper_player_id,
            }
            for r in rows
        ]
    }


def _tool_get_keeper_candidates(session: Session, team: str | None = None, **_: Any) -> dict:
    owner_user_id = settings.sleeper_owner_user_id
    if team:
        owner_user_id = resolve_owner(session, team).user_id
    try:
        candidates = compute_keeper_candidates(session, owner_user_id=owner_user_id)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "candidates": [
            {
                "name": c.name,
                "position": c.position,
                "team": c.team,
                "rank_ecr": c.rank_ecr,
                "cost_round": c.cost_round,
                "value_surplus": c.value_surplus,
                "reasoning": c.reasoning,
            }
            for c in candidates
        ]
    }


def _tool_evaluate_trade(
    session: Session,
    team_a: str,
    team_a_gives: list[str],
    team_b: str,
    team_b_gives: list[str],
    **_: Any,
) -> dict:
    league_id = _league_id()
    owner_a = resolve_owner(session, team_a)
    owner_b = resolve_owner(session, team_b)
    roster_a = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner_a.user_id).one()
    roster_b = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner_b.user_id).one()

    a_ids = _resolve_players_on_roster(session, roster_a, team_a_gives)
    b_ids = _resolve_players_on_roster(session, roster_b, team_b_gives)

    try:
        result = _evaluate_trade_pipeline(session, owner_a.user_id, a_ids, owner_b.user_id, b_ids)
    except (RuntimeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc

    return {
        "side_a": {"team": result.side_a.team_name, "reasoning": result.side_a.reasoning},
        "side_b": {"team": result.side_b.team_name, "reasoning": result.side_b.reasoning},
        "verdict": result.verdict,
    }


def _tool_get_best_available(session: Session, team: str | None = None, limit: int = 15, **_: Any) -> dict:
    owner_user_id = settings.sleeper_owner_user_id
    if team:
        owner_user_id = resolve_owner(session, team).user_id
    try:
        players = _get_best_available_pipeline(session, owner_user_id=owner_user_id, limit=limit)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "best_available": [
            {
                "name": p.name,
                "position": p.position,
                "team": p.team,
                "rank_ecr": p.rank_ecr,
                "pos_rank": p.pos_rank,
                "reasoning": p.reasoning,
            }
            for p in players
        ]
    }


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_league_info",
        "description": "Get this league's settings: scoring, roster positions, keeper rules, trade deadline.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_rosters",
        "description": "List every team in the league with its record and position counts, to compare team needs.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "search_player",
        "description": "Look up a player's Sleeper player_id and info by (partial) name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Player name or partial name"},
                "limit": {"type": "integer"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_roster",
        "description": "Get a specific team's full roster with each player's current FantasyPros rank.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or owner display name (partial match ok)"}
            },
            "required": ["team"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_rankings",
        "description": "Get cached FantasyPros dynasty/superflex rankings, optionally filtered by position or name search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "position": {"type": "string", "description": "e.g. QB, RB, WR, TE, K, DEF"},
                "search": {"type": "string", "description": "Substring to match against player names"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_keeper_candidates",
        "description": (
            "Rank a team's roster by keeper value (cost round vs. expected value at that draft slot). "
            "Defaults to your team if `team` is omitted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"team": {"type": "string", "description": "Team name (defaults to your team)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "evaluate_trade",
        "description": "Evaluate a proposed trade between two teams: value swing and roster-need impact for both sides.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_a": {"type": "string", "description": "First team's name"},
                "team_a_gives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Player names team_a is trading away",
                },
                "team_b": {"type": "string", "description": "Second team's name"},
                "team_b_gives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Player names team_b is trading away",
                },
            },
            "required": ["team_a", "team_a_gives", "team_b", "team_b_gives"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_best_available",
        "description": (
            "During a live draft: get the best available players not yet drafted (polled live from "
            "Sleeper) and not already on the roster, ranked by value with roster-need context for each. "
            "Defaults to your team if `team` is omitted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name (defaults to your team)"},
                "limit": {"type": "integer", "description": "Max players to return (default 15)"},
            },
            "additionalProperties": False,
        },
    },
]

TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_league_info": _tool_get_league_info,
    "list_rosters": _tool_list_rosters,
    "search_player": _tool_search_player,
    "get_roster": _tool_get_roster,
    "get_rankings": _tool_get_rankings,
    "get_keeper_candidates": _tool_get_keeper_candidates,
    "get_best_available": _tool_get_best_available,
    "evaluate_trade": _tool_evaluate_trade,
}
