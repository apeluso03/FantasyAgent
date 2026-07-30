"""Matches FantasyPros players to Sleeper player IDs.

This is the fiddly part the spec calls out: name formats differ between the
two sources ("Patrick Mahomes II" vs "Patrick Mahomes", suffixes, hyphens,
apostrophes), and defenses are named as team names on FantasyPros ("Houston
Texans") vs a bare team code on Sleeper ("HOU"). Strategy, in priority order:

1. Manual alias override (`PlayerAlias`, keyed by FantasyPros player ID) —
   always wins, for the cases automatic matching gets wrong.
2. Defenses: match on team code directly (after resolving FantasyPros/Sleeper
   team-code differences like JAC vs JAX) rather than by name.
3. Exact match on normalized name + position.
4. Fuzzy match on normalized name within the same position, above a
   similarity threshold.

Unmatched players are returned to the caller rather than silently dropped,
so they can be reviewed and turned into aliases.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Iterable

from ..db.models import PlayerRecord
from .schemas import RankedPlayer

# FantasyPros -> Sleeper position codes, where they differ.
POSITION_ALIASES = {"DST": "DEF"}

# FantasyPros -> Sleeper team codes, where they differ.
TEAM_ALIASES = {"JAC": "JAX"}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")

FUZZY_MATCH_THRESHOLD = 0.88


def normalize_name(name: str) -> str:
    lowered = name.lower().replace("-", " ").replace(".", "")
    stripped = _NON_ALNUM.sub("", lowered)
    tokens = [t for t in stripped.split() if t not in _SUFFIXES]
    return " ".join(tokens)


def normalize_position(position: str) -> str:
    return POSITION_ALIASES.get(position, position)


def normalize_team(team: str | None) -> str | None:
    if team is None:
        return None
    return TEAM_ALIASES.get(team, team)


@dataclass
class MatchResult:
    fp_player_id: int
    name: str
    position: str
    sleeper_player_id: str | None
    method: str  # "alias" | "team_code" | "exact_name" | "fuzzy_name" | "unmatched"
    confidence: float


class SleeperPlayerIndex:
    """Lookup structures built from the cached Sleeper player table."""

    def __init__(self, players: Iterable[PlayerRecord]) -> None:
        self._by_name_position: dict[tuple[str, str], list[str]] = {}
        self._names_by_position: dict[str, list[tuple[str, str]]] = {}
        self._def_by_team: dict[str, str] = {}

        for player in players:
            if player.position == "DEF" and player.team:
                self._def_by_team[player.team] = player.player_id
            if not player.full_name or not player.position:
                continue
            norm = normalize_name(player.full_name)
            key = (norm, player.position)
            self._by_name_position.setdefault(key, []).append(player.player_id)
            self._names_by_position.setdefault(player.position, []).append((norm, player.player_id))

    def defense_by_team(self, team: str) -> str | None:
        return self._def_by_team.get(team)

    def exact(self, normalized_name: str, position: str) -> list[str]:
        return self._by_name_position.get((normalized_name, position), [])

    def fuzzy(self, normalized_name: str, position: str) -> tuple[str, float] | None:
        candidates = self._names_by_position.get(position, [])
        if not candidates:
            return None
        best_id: str | None = None
        best_ratio = 0.0
        for cand_name, player_id in candidates:
            ratio = difflib.SequenceMatcher(None, normalized_name, cand_name).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_id = player_id
        if best_id is not None and best_ratio >= FUZZY_MATCH_THRESHOLD:
            return best_id, best_ratio
        return None


def match_player(
    ranked: RankedPlayer,
    index: SleeperPlayerIndex,
    aliases: dict[int, str],
) -> MatchResult:
    if ranked.fp_player_id in aliases:
        return MatchResult(
            fp_player_id=ranked.fp_player_id,
            name=ranked.name,
            position=ranked.position,
            sleeper_player_id=aliases[ranked.fp_player_id],
            method="alias",
            confidence=1.0,
        )

    position = normalize_position(ranked.position)

    if position == "DEF":
        team = normalize_team(ranked.team)
        sleeper_id = index.defense_by_team(team) if team else None
        return MatchResult(
            fp_player_id=ranked.fp_player_id,
            name=ranked.name,
            position=ranked.position,
            sleeper_player_id=sleeper_id,
            method="team_code" if sleeper_id else "unmatched",
            confidence=1.0 if sleeper_id else 0.0,
        )

    normalized = normalize_name(ranked.name)
    exact_matches = index.exact(normalized, position)
    if len(exact_matches) == 1:
        return MatchResult(
            fp_player_id=ranked.fp_player_id,
            name=ranked.name,
            position=ranked.position,
            sleeper_player_id=exact_matches[0],
            method="exact_name",
            confidence=1.0,
        )

    if not exact_matches:
        fuzzy = index.fuzzy(normalized, position)
        if fuzzy is not None:
            sleeper_id, ratio = fuzzy
            return MatchResult(
                fp_player_id=ranked.fp_player_id,
                name=ranked.name,
                position=ranked.position,
                sleeper_player_id=sleeper_id,
                method="fuzzy_name",
                confidence=ratio,
            )

    # Either no candidate at all, or more than one same-name/same-position
    # player (ambiguous) — surface as unmatched rather than guessing.
    return MatchResult(
        fp_player_id=ranked.fp_player_id,
        name=ranked.name,
        position=ranked.position,
        sleeper_player_id=None,
        method="unmatched",
        confidence=0.0,
    )
