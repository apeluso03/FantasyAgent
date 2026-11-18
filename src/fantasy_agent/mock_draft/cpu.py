"""CPU drafter: best available by ADP, bent by team need.

Used for every unclaimed team, for a seated person with autopick on, and when
a person's pick clock runs out (after trying their queue first).

The model is deliberately simple and explainable -- "take the best player on
the board unless the roster badly needs something else" -- rather than a
projection-based optimizer:

1. Hard rules first: never draft a position the league doesn't start; never
   draft a K/DEF onto the bench, and only take one in the team's last few
   picks; once a team's remaining picks only just cover its unfilled starting
   slots, it *must* fill one.
2. Soft score for everything else: ADP (plus noise, so mocks vary), discounted
   when the player fills a starting slot and penalized the deeper the team
   already is at that position.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .engine import FLEX_ELIGIBLE, SUPER_FLEX_ELIGIBLE, DraftState, unfilled_starters

# How many of the top remaining players (by ADP) the CPU actually weighs --
# keeps a big need multiplier from dragging a 300th-ranked player into round 2.
CANDIDATE_WINDOW = 30


@dataclass(frozen=True)
class PoolPlayer:
    player_id: str
    position: str
    adp: float


def _fill_kind(position: str, need: dict[str, int]) -> str:
    if need.get(position, 0) > 0:
        return "starter"
    if position in FLEX_ELIGIBLE and need.get("FLEX", 0) > 0:
        return "flex"
    if position in SUPER_FLEX_ELIGIBLE and need.get("SUPER_FLEX", 0) > 0:
        return "flex"
    return "bench"


def _bench_cap(position: str, slots: dict[str, int]) -> int:
    """Most players a CPU will roster at a position before it stops
    considering more (unless nothing else is left)."""
    sf = slots.get("SUPER_FLEX", 0)
    flex = slots.get("FLEX", 0)
    bench = slots.get("BN", 0)
    if position == "QB":
        return slots.get("QB", 0) + sf + (1 if bench else 0)
    if position == "TE":
        return slots.get("TE", 0) + (1 if bench >= 4 else 0)
    if position in ("K", "DEF"):
        return slots.get(position, 0)
    # RB/WR soak up most bench spots.
    return slots.get(position, 0) + flex + sf + max(1, bench // 2)


def choose_player(
    state: DraftState,
    team_id: int,
    available: Iterable[PoolPlayer],
    *,
    position_of: dict[str, str],
    rng: random.Random,
) -> str | None:
    """Pick a player for `team_id` from `available` (already excluding
    drafted players). Returns None only if `available` is empty."""
    slots = state.settings.roster_slots
    team_picks = [p for p in state.picks if p.owner_team_id == team_id]
    picks_left = sum(1 for p in team_picks if p.player_id is None)
    roster = [p.player_id for p in team_picks if p.player_id]
    counts = Counter(position_of.get(pid, "") for pid in roster)
    need = unfilled_starters(counts, slots)
    required_left = sum(need.values())
    kdef_needed = sum(need.get(pos, 0) for pos in ("K", "DEF"))

    usable_positions = {
        pos
        for pos in ("QB", "RB", "WR", "TE", "K", "DEF")
        if slots.get(pos, 0) > 0
        or (pos in FLEX_ELIGIBLE and slots.get("FLEX", 0) > 0)
        or (pos in SUPER_FLEX_ELIGIBLE and slots.get("SUPER_FLEX", 0) > 0)
    }

    ordered = sorted(available, key=lambda p: p.adp)
    if not ordered:
        return None

    def allowed(p: PoolPlayer, *, strict: bool) -> bool:
        if p.position not in usable_positions:
            return False
        kind = _fill_kind(p.position, need)
        if p.position in ("K", "DEF"):
            # Only in the final picks, and only into an open K/DEF slot.
            return kind == "starter" and picks_left <= kdef_needed + 1
        if picks_left <= required_left and kind == "bench":
            return False
        if picks_left <= kdef_needed and kind != "starter":
            return False
        at_cap = counts.get(p.position, 0) >= _bench_cap(p.position, slots)
        # TEs are capped even when they'd technically fill FLEX/SUPER_FLEX --
        # nobody starts a third TE, so a CPU shouldn't draft one to do it.
        if strict and at_cap and (kind == "bench" or p.position == "TE"):
            return False
        return True

    candidates = [p for p in ordered if allowed(p, strict=True)][:CANDIDATE_WINDOW]
    if not candidates:
        candidates = [p for p in ordered if allowed(p, strict=False)][:CANDIDATE_WINDOW]
    if not candidates:
        # Nothing fits the rules (tiny pool, odd roster settings) -- just take the best left.
        return ordered[0].player_id

    randomness = max(0.0, state.settings.cpu_randomness)

    def score(p: PoolPlayer) -> float:
        noise = rng.gauss(0.0, randomness * (1.0 + 0.05 * p.adp)) if randomness else 0.0
        eff = max(1.0, p.adp + noise)
        kind = _fill_kind(p.position, need)
        if p.position in ("K", "DEF"):
            # Allowed at all only when it's time; then it's the priority.
            return eff * 0.01
        if kind == "starter":
            mult = 0.88
        elif kind == "flex" and (p.position == "QB" or need.get("FLEX", 0) > 0):
            mult = 0.95
        elif kind == "flex":
            # Only fills SUPER_FLEX as a non-QB: real drafters chase a QB
            # there, so no need bonus.
            mult = 1.0
        else:
            depth = max(0, counts.get(p.position, 0) - slots.get(p.position, 0))
            mult = 1.0 + 0.1 * depth
        # Must-fill pressure: the fewer spare picks, the more a starter fill matters.
        spare = picks_left - required_left
        if kind != "bench" and spare <= 2:
            mult *= 0.8
        return eff * mult

    return min(candidates, key=score).player_id


def autopick(
    state: DraftState,
    team_id: int,
    available: list[PoolPlayer],
    *,
    position_of: dict[str, str],
    queue: list[str] | None,
    rng: random.Random,
) -> str | None:
    """A person's timeout/autopick: the first still-available player in
    their queue, else whatever the CPU would take."""
    if queue:
        available_ids = {p.player_id for p in available}
        for pid in queue:
            if pid in available_ids:
                return pid
    return choose_player(state, team_id, available, position_of=position_of, rng=rng)
