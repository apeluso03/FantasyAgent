"""Recent-performance snapshot for a single player -- feeds the Best
Available tab's expandable row. Pure data/heuristics, no LLM (same spirit as
draft.py/keeper.py: "no LLM" is the whole point of these pipeline modules --
the agent is reserved for the chat tab). Fast enough to run synchronously off
a click without a round trip through the tool-calling agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import settings
from .sleeper.client import SleeperClient

# How many weeks of stats a single lookup will scan backward before giving up
# on finding `games_back` games with a played stat line (covers bye weeks and
# short injury stretches without scanning indefinitely).
_MAX_WEEKS_SCANNED = 15

_STAT_KEYS_BY_POSITION: dict[str, list[tuple[str, str]]] = {
    "QB": [("pass_yd", "pass yd"), ("pass_td", "pass TD"), ("rush_yd", "rush yd"), ("int", "INT")],
    "RB": [("rush_att", "car"), ("rush_yd", "rush yd"), ("rush_td", "rush TD"), ("rec", "rec"), ("rec_yd", "rec yd")],
    "WR": [("rec", "rec"), ("rec_yd", "rec yd"), ("rec_td", "rec TD"), ("rush_yd", "rush yd")],
    "TE": [("rec", "rec"), ("rec_yd", "rec yd"), ("rec_td", "rec TD")],
    "K": [("fgm", "FG"), ("xpm", "XP")],
    "DEF": [("def_sack", "sack"), ("def_int", "INT"), ("def_td", "TD")],
}

# In-process cache of weekly stat dumps (each covers every NFL player, so it's
# worth reusing across different players' lookups within the same app run).
# Never persisted to disk: a completed week's stats don't change, but there's
# no reason to carry this across app restarts either.
_stats_cache: dict[tuple[str, int], dict] = {}


@dataclass
class GameLine:
    week: int
    points_ppr: float | None
    stat_line: str


@dataclass
class PlayerAnalysis:
    player_id: str
    season: str
    games: list[GameLine] = field(default_factory=list)  # most recent first
    avg_points: float | None = None
    blurb: str = ""


def _cached_week_stats(client: SleeperClient, season: str, week: int) -> dict:
    key = (season, week)
    if key not in _stats_cache:
        _stats_cache[key] = client.get_week_stats(season, week)
    return _stats_cache[key]


def _format_stat_line(stats: dict, position: str | None) -> str:
    parts = []
    for key, label in _STAT_KEYS_BY_POSITION.get(position or "", []):
        value = stats.get(key)
        if value:
            parts.append(f"{value:g} {label}")
    return ", ".join(parts) if parts else "no stats recorded"


def _trend_blurb(scored: list[float]) -> str:
    """`scored` is most-recent-first PPR point totals."""
    if not scored:
        return "No recent game logs found for this player."
    if len(scored) == 1:
        return f"Only one recent game on record: {scored[0]:.1f} PPR points."

    avg = sum(scored) / len(scored)
    most_recent = scored[0]
    older_avg = sum(scored[1:]) / len(scored[1:])
    diff = most_recent - older_avg
    if diff >= 5:
        direction = "trending up"
    elif diff <= -5:
        direction = "trending down"
    else:
        direction = "holding fairly steady"

    swing = max(scored) - min(scored)
    volatility = "boom-or-bust week to week" if swing >= 12 else "fairly consistent week to week"

    return (
        f"Averaging {avg:.1f} PPR points over the last {len(scored)} games and {direction} "
        f"(most recent: {most_recent:.1f}). Has been {volatility}."
    )


def get_player_analysis(
    player_id: str,
    *,
    position: str | None,
    games_back: int = 5,
    client: SleeperClient | None = None,
) -> PlayerAnalysis:
    owns_client = client is None
    client = client or SleeperClient(base_url=settings.sleeper_base_url)
    try:
        state = client.get_nfl_state()
        if state.season_type == "regular" and state.week > 1:
            season = state.season
            start_week = state.week - 1
        else:
            # Preseason/offseason: current season has no completed games yet,
            # so fall back to the end of last season instead of showing nothing.
            season = state.previous_season or str(int(state.season) - 1)
            start_week = 18

        games: list[GameLine] = []
        week = start_week
        scanned = 0
        while week >= 1 and len(games) < games_back and scanned < _MAX_WEEKS_SCANNED:
            week_stats = _cached_week_stats(client, season, week)
            player_stats = week_stats.get(player_id)
            if player_stats:
                games.append(
                    GameLine(
                        week=week,
                        points_ppr=player_stats.get("pts_ppr"),
                        stat_line=_format_stat_line(player_stats, position),
                    )
                )
            week -= 1
            scanned += 1
    finally:
        if owns_client:
            client.close()

    scored = [g.points_ppr for g in games if g.points_ppr is not None]
    avg_points = sum(scored) / len(scored) if scored else None

    return PlayerAnalysis(
        player_id=player_id,
        season=season,
        games=games,
        avg_points=avg_points,
        blurb=_trend_blurb(scored),
    )
