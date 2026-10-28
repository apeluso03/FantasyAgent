"""League standings and a rough playoff outlook per team.

The outlook is what lets the agent decide a trade question should be judged
on long-term (dynasty) value instead of the win-now default: a team that's
realistically out of the playoff race should be selling for the future.

It's a deliberately simple heuristic off games back of the last playoff seed
vs. regular-season games left -- not a playoff-odds simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from .db.models import LeagueRecord, RosterRecord, UserRecord

Outlook = Literal["in_position", "bubble", "long_shot", "eliminated", "unknown"]


@dataclass
class TeamStanding:
    owner_id: str | None
    team_name: str
    wins: int
    losses: int
    ties: int
    points_for: float
    seed: int
    games_back: float  # of the last playoff seed; 0 when in position
    games_remaining: int | None  # regular-season games left; None if unknown
    outlook: Outlook


def playoff_outlook(games_back: float, games_remaining: int | None, *, in_position: bool) -> Outlook:
    if in_position:
        return "in_position"
    if games_remaining is None:
        return "unknown"
    if games_back > games_remaining:
        return "eliminated"  # can't catch the current last seed even winning out
    if games_back >= 2 and games_back > games_remaining / 3:
        return "long_shot"
    return "bubble"


def compute_standings(session: Session, league_id: str) -> list[TeamStanding]:
    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data. Run `fantasy-agent sync` first.")
    playoff_teams = league.settings.get("playoff_teams")
    playoff_week_start = league.settings.get("playoff_week_start")
    last_scored_week = league.settings.get("last_scored_leg") or 0
    games_remaining = (
        max(0, playoff_week_start - 1 - last_scored_week) if playoff_week_start else None
    )

    users = {u.user_id: u for u in session.query(UserRecord).filter_by(league_id=league_id).all()}
    rows = []
    for roster in session.query(RosterRecord).filter_by(league_id=league_id).all():
        s = roster.settings or {}
        owner = users.get(roster.owner_id)
        rows.append(
            {
                "owner_id": roster.owner_id,
                "team_name": (owner.team_name or owner.display_name) if owner else "(unowned)",
                "wins": s.get("wins") or 0,
                "losses": s.get("losses") or 0,
                "ties": s.get("ties") or 0,
                "points_for": (s.get("fpts") or 0) + (s.get("fpts_decimal") or 0) / 100,
            }
        )

    def win_score(row: dict) -> float:
        return row["wins"] + 0.5 * row["ties"]

    # Sleeper's default tiebreaker after record is points for.
    rows.sort(key=lambda r: (win_score(r), r["points_for"]), reverse=True)
    cutoff = win_score(rows[playoff_teams - 1]) if playoff_teams and len(rows) >= playoff_teams else None

    standings = []
    for seed, row in enumerate(rows, start=1):
        in_position = cutoff is None or (playoff_teams is not None and seed <= playoff_teams)
        games_back = 0.0 if in_position else cutoff - win_score(row)
        standings.append(
            TeamStanding(
                **row,
                seed=seed,
                games_back=games_back,
                games_remaining=games_remaining,
                outlook=playoff_outlook(games_back, games_remaining, in_position=in_position)
                if cutoff is not None
                else "unknown",
            )
        )
    return standings
