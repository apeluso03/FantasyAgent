"""Which FantasyPros rankings page answers which question, per league format.

Three horizons, because "how good is this player" depends on when you care:

- weekly  -- this week's start/sit rankings
- ros     -- rest of season; the win-now default for trades and power rankings
- dynasty -- long-term value (age-weighted); keepers and rebuilding teams

Each horizon maps to a page for superflex leagues and one for 1-QB leagues.
FantasyPros has no rest-of-season *superflex* page (the URL redirects to the
1-QB one), so that one is derived here: see derive_superflex_order().
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from ..db.models import LeagueRecord

Horizon = Literal["weekly", "ros", "dynasty"]
HORIZONS: tuple[Horizon, ...] = ("weekly", "ros", "dynasty")

# Not a real FantasyPros URL -- built by sync.derive_ros_superflex() from the
# two source pages below, and stored under this slug like any scraped page.
DERIVED_ROS_SUPERFLEX = "ros-ppr-superflex-derived"
ROS_1QB = "ros-ppr-overall"
WEEKLY_SUPERFLEX = "ppr-superflex"

_PAGES: dict[Horizon, dict[bool, str]] = {
    # FantasyPros' only weekly page that ranks QBs alongside everyone else is
    # the superflex one, so 1-QB leagues use it too. That only skews QB-vs-
    # skill-player comparisons, which never come up in a 1-QB start/sit
    # decision (a QB can't fill a flex spot there); pos_rank is unaffected.
    "weekly": {True: WEEKLY_SUPERFLEX, False: WEEKLY_SUPERFLEX},
    "ros": {True: DERIVED_ROS_SUPERFLEX, False: ROS_1QB},
    "dynasty": {True: "dynasty-superflex", False: "dynasty-overall"},
}

# Every page that has to be scraped (the derived one is built from these).
SOURCE_PAGES: tuple[str, ...] = tuple(
    sorted({page for by_format in _PAGES.values() for page in by_format.values()} - {DERIVED_ROS_SUPERFLEX})
)
ALL_PAGES: tuple[str, ...] = (*SOURCE_PAGES, DERIVED_ROS_SUPERFLEX)

# Positions that compete with QBs for a superflex spot. K/DST don't, so they
# neither count toward nor get displaced by QB placement.
_SKILL_POSITIONS = {"RB", "WR", "TE"}


def is_superflex(roster_positions: list[str]) -> bool:
    """A league is superflex if a second QB can start: a SUPER_FLEX slot, or
    two dedicated QB slots (2QB leagues value QBs the same way)."""
    return "SUPER_FLEX" in roster_positions or roster_positions.count("QB") >= 2


def rankings_page(horizon: Horizon, *, superflex: bool) -> str:
    return _PAGES[horizon][superflex]


def rankings_page_for_league(session: Session, league_id: str, horizon: Horizon) -> str:
    league = session.get(LeagueRecord, league_id)
    if league is None:
        raise RuntimeError("No cached league data. Run `fantasy-agent sync` first.")
    return rankings_page(horizon, superflex=is_superflex(league.roster_positions or []))


def derive_superflex_order(base: list[tuple[str, str]], reference: list[str]) -> list[str]:
    """Re-slot QBs in a 1-QB ranking to superflex value.

    `base` is the 1-QB ranking as (key, position) pairs, best first. Its order
    *within* QBs and *within* non-QBs is kept as-is -- that's the part that
    doesn't depend on format. Only where QBs land relative to everyone else
    changes.

    `reference` is the positions of a superflex ranking, best first. It
    supplies the exchange rate: if the reference's 3rd QB has 4 skill players
    ahead of it, the base's 3rd QB goes right after the base's 4th skill
    player. QBs past the end of the reference keep the reference's average
    spacing over its last few QBs.

    Returns the base's keys in the new order.
    """
    skill_ahead: list[int] = []  # skill players ahead of the reference's k-th QB
    seen_skill = 0
    for position in reference:
        if position == "QB":
            skill_ahead.append(seen_skill)
        elif position in _SKILL_POSITIONS:
            seen_skill += 1

    qbs = [key for key, pos in base if pos == "QB"]
    others = [(key, pos) for key, pos in base if pos != "QB"]

    def slot(k: int) -> int:
        if k < len(skill_ahead):
            return skill_ahead[k]
        if not skill_ahead:
            return 10**9  # no reference QBs: leave QBs after everyone
        tail = skill_ahead[-6:]
        gap = (tail[-1] - tail[0]) / (len(tail) - 1) if len(tail) > 1 else 1
        return round(skill_ahead[-1] + gap * (k - len(skill_ahead) + 1))

    order: list[str] = []
    k = 0
    skill_placed = 0
    for key, pos in others:
        while k < len(qbs) and slot(k) <= skill_placed:
            order.append(qbs[k])
            k += 1
        order.append(key)
        if pos in _SKILL_POSITIONS:
            skill_placed += 1
    order.extend(qbs[k:])
    return order
