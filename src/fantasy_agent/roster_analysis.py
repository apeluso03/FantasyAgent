"""Roster-composition helpers shared by the trade analyzer and draft assistant.

FLEX/SUPER_FLEX slots aren't attributed to a single position here — see each
caller for how it handles that simplification.
"""

from __future__ import annotations

from .db.models import PlayerRecord

STANDARD_POSITIONS = ("QB", "RB", "WR", "TE")


def starter_requirements(roster_positions: list[str]) -> dict[str, int]:
    """Count of dedicated (non-FLEX) starter slots per position."""
    counts = {pos: 0 for pos in STANDARD_POSITIONS}
    for slot in roster_positions:
        if slot in counts:
            counts[slot] += 1
    return counts


def position_counts(player_ids: list[str], players_by_id: dict[str, PlayerRecord]) -> dict[str, int]:
    counts = {pos: 0 for pos in STANDARD_POSITIONS}
    for pid in player_ids:
        player = players_by_id.get(pid)
        if player and player.position in counts:
            counts[player.position] += 1
    return counts
