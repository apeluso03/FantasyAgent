"""Tools exposed to the agent's tool-calling loop.

Each tool pairs a JSON schema (what the model sees) with a handler that takes the
open DB session plus the tool's parsed input and returns a JSON-serializable
dict. Keeping tool outputs structured — not prose — lets the agent reason
over them directly rather than re-parsing text, per the spec's agent design
notes. Handlers read from the local cache, with two deliberate exceptions
that go to Sleeper live: get_best_available polls the draft endpoint, since
"who's been picked" can't be allowed to go stale mid-draft (see draft.py), and
get_player_recent_games pulls recent box scores (see player_analysis.py).

Rankings come in three horizons (weekly / ros / dynasty, see rankings/pages.py),
and every rankings-backed tool picks the page matching the league's format
(superflex vs 1-QB) itself, so the model only ever chooses the horizon.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import LeagueRecord, PlayerRecord, RankingRecord, RosterRecord, UserRecord
from ..draft import get_best_available as _get_best_available_pipeline
from ..keeper import compute_keeper_candidates
from ..player_analysis import get_player_analysis
from ..power_rankings import compute_power_rankings as _compute_power_rankings_pipeline
from ..rankings.matching import normalize_name
from ..rankings.pages import HORIZONS, Horizon, is_superflex, rankings_page_for_league
from ..roster_analysis import STANDARD_POSITIONS
from ..standings import TeamStanding, compute_standings
from ..trade import evaluate_trade as _evaluate_trade_pipeline

# evaluate_trade speaks in the user's terms; these are the rankings behind each.
TRADE_HORIZONS: dict[str, Horizon] = {"win_now": "ros", "long_term": "dynasty"}

_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


class ToolError(RuntimeError):
    """Raised by a tool handler; the message is sent back to the model as a function_call_output."""


def _league_id() -> str:
    return settings.sleeper_league_id


def _rankings_page(session: Session, horizon: Horizon) -> str:
    """The format-appropriate page for `horizon`, refusing to silently hand
    back an empty ranking (every rank would just come out None)."""
    if horizon not in HORIZONS:
        raise ToolError(f"Unknown horizon '{horizon}'. Use one of: {', '.join(HORIZONS)}")
    try:
        page = rankings_page_for_league(session, _league_id(), horizon)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    if session.query(RankingRecord.id).filter_by(source="fantasypros", page=page).first() is None:
        raise ToolError(f"No {horizon} rankings cached yet ('{page}'). Run `fantasy-agent rankings-sync` first.")
    return page


def _standings_by_owner(session: Session) -> dict[str | None, TeamStanding]:
    try:
        return {s.owner_id: s for s in compute_standings(session, _league_id())}
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc


def _standing_dict(s: TeamStanding | None) -> dict | None:
    if s is None:
        return None
    record = f"{s.wins}-{s.losses}" + (f"-{s.ties}" if s.ties else "")
    return {
        "record": record,
        "seed": s.seed,
        "games_back_of_playoffs": s.games_back,
        "regular_season_games_left": s.games_remaining,
        "playoff_outlook": s.outlook,
    }


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
    me = (
        session.query(UserRecord)
        .filter_by(league_id=_league_id(), user_id=settings.sleeper_owner_user_id)
        .one_or_none()
    )
    return {
        "name": league.name,
        # Who "I" / "my team" is -- without this, a "should I trade X?" question
        # leaves the model guessing which roster is the user's.
        "your_team": (me.team_name or me.display_name) if me else None,
        "season": league.season,
        "total_rosters": league.total_rosters,
        "format": "superflex" if is_superflex(league.roster_positions or []) else "1qb",
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
        "playoffs": {
            "playoff_teams": league.settings.get("playoff_teams"),
            "playoff_week_start": league.settings.get("playoff_week_start"),
            "last_scored_week": league.settings.get("last_scored_leg"),
        },
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
    standings = _standings_by_owner(session)

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
                "standing": _standing_dict(standings.get(r.owner_id)),
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


def _tool_get_roster(session: Session, team: str, horizon: Horizon = "ros", **_: Any) -> dict:
    league_id = _league_id()
    owner = resolve_owner(session, team)
    page = _rankings_page(session, horizon)
    roster = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner.user_id).one()
    players = session.query(PlayerRecord).filter(PlayerRecord.player_id.in_(roster.players)).all()
    rankings = {
        r.sleeper_player_id: r
        for r in session.query(RankingRecord)
        .filter_by(source="fantasypros", page=page)
        .filter(RankingRecord.sleeper_player_id.in_(roster.players))
        .all()
        if r.sleeper_player_id
    }
    return {
        "team_name": owner.team_name,
        "rankings_horizon": horizon,
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
    horizon: Horizon = "ros",
    **_: Any,
) -> dict:
    page = _rankings_page(session, horizon)
    rows = session.query(RankingRecord).filter_by(source="fantasypros", page=page).all()
    if position:
        rows = [r for r in rows if r.position == position.upper()]
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in r.name.lower()]
    rows.sort(key=lambda r: r.rank_ecr)
    rows = rows[:limit]
    return {
        "rankings_horizon": horizon,
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
    # Keeping a player is a bet on next season, so this is always dynasty value.
    page = _rankings_page(session, "dynasty")
    try:
        candidates = compute_keeper_candidates(session, owner_user_id=owner_user_id, rankings_page=page)
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


def _injury_note_dict(note) -> dict:
    return {"name": note.name, "status": note.injury_status, "multiplier": note.multiplier, "reason": note.reason}


def _tool_evaluate_trade(
    session: Session,
    team_a: str,
    team_a_gives: list[str],
    team_b: str,
    team_b_gives: list[str],
    horizon: str = "win_now",
    **_: Any,
) -> dict:
    if horizon not in TRADE_HORIZONS:
        raise ToolError(f"Unknown horizon '{horizon}'. Use one of: {', '.join(TRADE_HORIZONS)}")
    league_id = _league_id()
    owner_a = resolve_owner(session, team_a)
    owner_b = resolve_owner(session, team_b)
    roster_a = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner_a.user_id).one()
    roster_b = session.query(RosterRecord).filter_by(league_id=league_id, owner_id=owner_b.user_id).one()

    a_ids = _resolve_players_on_roster(session, roster_a, team_a_gives)
    b_ids = _resolve_players_on_roster(session, roster_b, team_b_gives)

    page = _rankings_page(session, TRADE_HORIZONS[horizon])
    try:
        result = _evaluate_trade_pipeline(session, owner_a.user_id, a_ids, owner_b.user_id, b_ids, rankings_page=page)
    except (RuntimeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    standings = _standings_by_owner(session)

    return {
        "horizon": horizon,
        "side_a": {
            "team": result.side_a.team_name,
            "standing": _standing_dict(standings.get(owner_a.user_id)),
            "reasoning": result.side_a.reasoning,
            "injured_players_given": [_injury_note_dict(n) for n in result.side_a.injured_players_given],
            "injured_players_received": [_injury_note_dict(n) for n in result.side_a.injured_players_received],
        },
        "side_b": {
            "team": result.side_b.team_name,
            "standing": _standing_dict(standings.get(owner_b.user_id)),
            "reasoning": result.side_b.reasoning,
            "injured_players_given": [_injury_note_dict(n) for n in result.side_b.injured_players_given],
            "injured_players_received": [_injury_note_dict(n) for n in result.side_b.injured_players_received],
        },
        "verdict": result.verdict,
    }


def _tool_get_best_available(session: Session, team: str | None = None, limit: int = 15, **_: Any) -> dict:
    owner_user_id = settings.sleeper_owner_user_id
    if team:
        owner_user_id = resolve_owner(session, team).user_id
    # Unchanged from before horizons existed (dynasty, keeper-league drafts),
    # just format-aware now.
    page = _rankings_page(session, "dynasty")
    try:
        players = _get_best_available_pipeline(session, owner_user_id=owner_user_id, limit=limit, rankings_page=page)
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


def _tool_get_power_rankings(session: Session, horizon: Horizon = "ros", **_: Any) -> dict:
    page = _rankings_page(session, horizon)
    try:
        teams = _compute_power_rankings_pipeline(session, rankings_page=page)
    except RuntimeError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "rankings_horizon": horizon,
        "rankings": [
            {
                "rank": t.rank,
                "team": t.team_name,
                "starting_lineup_value": round(t.starting_lineup_value, 1),
                "average_starter_rank": (
                    round(t.average_starter_rank, 1) if t.average_starter_rank is not None else None
                ),
                "positional_rank": {pos: t.positional_rank[pos] for pos in STANDARD_POSITIONS},
                "injured_players": [_injury_note_dict(n) for n in t.injured_players],
            }
            for t in teams
        ]
    }


def _resolve_player(session: Session, name: str) -> PlayerRecord:
    """Find one fantasy-relevant player by (partial) name. Ties go to players
    rostered in this league, since that's who questions are almost always
    about (e.g. Josh Allen the QB, not Josh Allen the linebacker)."""
    norm = normalize_name(name)
    candidates = [
        p for p in session.query(PlayerRecord).filter(PlayerRecord.position.in_(_FANTASY_POSITIONS)).all()
        if p.full_name
    ]
    matches = [p for p in candidates if normalize_name(p.full_name) == norm] or [
        p for p in candidates if norm in normalize_name(p.full_name)
    ]
    if len(matches) > 1:
        rostered = {
            pid for r in session.query(RosterRecord).filter_by(league_id=_league_id()).all() for pid in r.players
        }
        matches = [p for p in matches if p.player_id in rostered] or matches
    if not matches:
        raise ToolError(f"No player matches '{name}'.")
    if len(matches) > 1:
        options = ", ".join(f"{p.full_name} ({p.position}, {p.team or 'FA'})" for p in matches[:8])
        raise ToolError(f"'{name}' matches multiple players ({options}). Be more specific.")
    return matches[0]


def _tool_get_player_recent_games(session: Session, player: str, games: int = 5, **_: Any) -> dict:
    p = _resolve_player(session, player)
    try:
        analysis = get_player_analysis(p.player_id, position=p.position, games_back=max(1, min(games, 10)))
    except httpx.HTTPError as exc:
        raise ToolError(f"Couldn't reach Sleeper for recent stats: {exc}") from exc
    return {
        "name": p.full_name,
        "position": p.position,
        "team": p.team,
        "injury_status": p.injury_status,
        "season": analysis.season,
        "games": [
            {"week": g.week, "points_ppr": g.points_ppr, "stat_line": g.stat_line} for g in analysis.games
        ],
        "avg_points_ppr": round(analysis.avg_points, 1) if analysis.avg_points is not None else None,
        "trend": analysis.blurb,
    }


def _tool(name: str, description: str, parameters: dict) -> dict:
    """Build a tool definition in the OpenAI Responses API's flat function-tool
    shape: {type, name, description, parameters} at the top level (not nested
    under a "function" key the way the older Chat Completions API does it)."""
    return {"type": "function", "name": name, "description": description, "parameters": parameters}


_HORIZON_PARAM = {
    "type": "string",
    "enum": list(HORIZONS),
    "description": (
        "Which rankings: 'ros' = rest of season (default; win-now value), 'weekly' = this week's "
        "start/sit, 'dynasty' = long-term value (keepers, rebuilding)"
    ),
}


TOOL_SCHEMAS: list[dict] = [
    _tool(
        "get_league_info",
        "Get this league's settings: which team is the user's (your_team -- who 'I'/'my team' means), "
        "format (superflex or 1qb), scoring, roster positions, keeper rules, trade deadline, playoff setup.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "list_rosters",
        (
            "List every team in the league with its record, playoff standing/outlook (in_position, bubble, "
            "long_shot, eliminated), and position counts, to compare team needs."
        ),
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _tool(
        "search_player",
        "Look up a player's Sleeper player_id and info by (partial) name.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Player name or partial name"},
                "limit": {"type": "integer"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "get_roster",
        "Get a specific team's full roster with each player's current FantasyPros rank.",
        {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name or owner display name (partial match ok)"},
                "horizon": _HORIZON_PARAM,
            },
            "required": ["team"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "get_rankings",
        (
            "Get cached FantasyPros rankings (already matched to this league's superflex/1-QB format), "
            "optionally filtered by position or name search."
        ),
        {
            "type": "object",
            "properties": {
                "position": {"type": "string", "description": "e.g. QB, RB, WR, TE, K, DEF"},
                "search": {"type": "string", "description": "Substring to match against player names"},
                "limit": {"type": "integer"},
                "horizon": _HORIZON_PARAM,
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "get_keeper_candidates",
        (
            "Rank a team's roster by keeper value (cost round vs. expected value at that draft slot), "
            "using dynasty rankings. Defaults to your team if `team` is omitted."
        ),
        {
            "type": "object",
            "properties": {"team": {"type": "string", "description": "Team name (defaults to your team)"}},
            "additionalProperties": False,
        },
    ),
    _tool(
        "evaluate_trade",
        (
            "Evaluate a proposed trade between two teams: value swing, roster-need impact, and each team's "
            "playoff standing. Judged on win-now (rest-of-season) value by default."
        ),
        {
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
                "horizon": {
                    "type": "string",
                    "enum": list(TRADE_HORIZONS),
                    "description": (
                        "'win_now' (default) = rest-of-season value. 'long_term' = dynasty value: use only when "
                        "the user asks about long-term/dynasty/keeper value, or the team being advised is a "
                        "playoff long_shot or eliminated"
                    ),
                },
            },
            "required": ["team_a", "team_a_gives", "team_b", "team_b_gives"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "get_best_available",
        (
            "During a live draft: get the best available players not yet drafted (polled live from "
            "Sleeper) and not already on the roster, ranked by value with roster-need context for each. "
            "Defaults to your team if `team` is omitted."
        ),
        {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name (defaults to your team)"},
                "limit": {"type": "integer", "description": "Max players to return (default 15)"},
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "get_power_rankings",
        (
            "Rank every team 1-N by best-possible-starting-lineup value (FantasyPros rankings), "
            "plus each team's QB/RB/WR/TE positional rank among the league -- use this to answer "
            "questions about how teams compare, or where a team is strong or thin by position."
        ),
        {"type": "object", "properties": {"horizon": _HORIZON_PARAM}, "additionalProperties": False},
    ),
    _tool(
        "get_player_recent_games",
        (
            "Get a player's most recent games (PPR points and stat line per week, live from Sleeper) plus an "
            "average and trend. Use it to check whether actual production backs up a player's ranking."
        ),
        {
            "type": "object",
            "properties": {
                "player": {"type": "string", "description": "Player name (partial match ok)"},
                "games": {"type": "integer", "description": "How many recent games (default 5, max 10)"},
            },
            "required": ["player"],
            "additionalProperties": False,
        },
    ),
]

TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_league_info": _tool_get_league_info,
    "list_rosters": _tool_list_rosters,
    "search_player": _tool_search_player,
    "get_roster": _tool_get_roster,
    "get_rankings": _tool_get_rankings,
    "get_keeper_candidates": _tool_get_keeper_candidates,
    "get_best_available": _tool_get_best_available,
    "get_power_rankings": _tool_get_power_rankings,
    "evaluate_trade": _tool_evaluate_trade,
    "get_player_recent_games": _tool_get_player_recent_games,
}
