"""Builds the mock draft's ADP board for the 2027 season.

No source publishes 2027 superflex ADP yet (as of late 2026), so the board is
a blend of what *does* exist, all superflex/2QB:

- Sleeper redraft ADP (`adp_2qb`) for the current season -- real drafts on
  Sleeper, i.e. what a player is worth *now*.
- Sleeper dynasty ADP (`adp_dynasty_2qb`) -- real dynasty startups, which
  already price in age and long-term outlook.
- FantasyPros dynasty superflex consensus rankings (expert ECR), averaged with
  Sleeper's dynasty ADP where both have the player.
- The incoming 2027 rookie class from a seed file (rookies_2027.json). These
  players are still in college, so they have no Sleeper ID or ADP anywhere;
  their rookie rank is mapped onto the overall board by a simple curve.

Three boards come out of that, one per `adp_mode`:

- "2027" (default): halfway between redraft-now and dynasty -- next year's
  value. Young risers move up, aging vets slide.
- "dynasty": dynasty only (a startup draft).
- "redraft": current-season redraft only, rookies pushed late.

Every board's final ADP is the player's ordinal position after merging, so a
rookie slotted at 12 pushes the veteran previously at 12 to 13 -- the board
always reads as "where this player goes in a draft that includes everyone".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import httpx

from ..rankings.matching import SleeperPlayerIndex, match_player
from ..rankings.schemas import RankedPlayer

SLEEPER_PROJECTIONS_URL = "https://api.sleeper.com/projections/nfl/{season}"
BOARD_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
NO_ADP = 999.0

ROOKIE_SEED_PATH = Path(__file__).with_name("rookies_2027.json")

# Where the rookie class lands on each board: overall = offset + spacing * (rank - 1).
# In superflex startups the consensus 1.01 rookie goes around the end of
# round 1, and the class thins out to roughly one rookie every ~5 picks.
ROOKIE_CURVES: dict[str, tuple[float, float]] = {
    "2027": (16.0, 5.0),
    "dynasty": (12.0, 4.6),
    "redraft": (45.0, 7.5),
}

# Weight on redraft ADP for the 2027 board (the rest is dynasty).
REDRAFT_WEIGHT_2027 = 0.5
# Players with redraft ADP but no dynasty ADP are almost always aging vets
# dynasty drafters have stopped taking -- nudge them down a year out.
REDRAFT_ONLY_PENALTY = 1.15


@dataclass
class BoardPlayer:
    player_id: str
    name: str
    position: str
    team: str | None
    adp_2027: float
    adp_dynasty: float
    adp_redraft: float
    is_rookie: bool = False
    college: str | None = None
    years_exp: int | None = None
    sources: list[str] = field(default_factory=list)

    def adp_for(self, mode: str) -> float:
        return {"2027": self.adp_2027, "dynasty": self.adp_dynasty, "redraft": self.adp_redraft}[mode]


# -- fetching ----------------------------------------------------------------


def fetch_sleeper_projections(
    season: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 30.0
) -> list[dict]:
    """Sleeper's season projections, which carry ADP per format. Undocumented
    but public (the same endpoint Sleeper's own web app reads)."""
    params = [("season_type", "regular"), ("order_by", "adp_2qb")]
    params += [("position[]", pos) for pos in BOARD_POSITIONS]
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(SLEEPER_PROJECTIONS_URL.format(season=season), params=params)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, list) else []


def load_rookie_seed(path: Path | None = None) -> list[dict]:
    raw = json.loads((path or ROOKIE_SEED_PATH).read_text(encoding="utf-8"))
    players = raw["players"] if isinstance(raw, dict) else raw
    return sorted(players, key=lambda p: p["rank"])


# -- combining -------------------------------------------------------------


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def rookie_player_id(name: str, season: int = 2027) -> str:
    # Not in Sleeper's database until after the NFL draft, so these get a
    # stable synthetic ID instead (and the frontend falls back to initials).
    return f"r{season % 100}-{_slug(name)}"


def _name(row: dict) -> str:
    p = row.get("player") or {}
    if p.get("position") == "DEF":
        return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or row.get("player_id", "")
    return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()


def _adp(row: dict, key: str) -> float:
    value = (row.get("stats") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) and value < NO_ADP else NO_ADP


def _ordinal(values: dict[str, float]) -> dict[str, float]:
    """Re-number by sort order (1, 2, 3, ...) so every board reads as draft slots."""
    ordered = sorted(values, key=lambda k: (values[k], k))
    return {k: float(i) for i, k in enumerate(ordered, start=1)}


def build_board(
    sleeper_rows: list[dict],
    fp_dynasty: list[RankedPlayer],
    rookies: list[dict],
    *,
    include_rookies: bool = True,
) -> list[BoardPlayer]:
    vets: dict[str, dict] = {}
    for row in sleeper_rows:
        p = row.get("player") or {}
        pos = p.get("position")
        pid = row.get("player_id")
        if pos not in BOARD_POSITIONS or not pid:
            continue
        vets[pid] = {
            "name": _name(row),
            "position": pos,
            "team": row.get("team") or p.get("team"),
            "years_exp": p.get("years_exp"),
            "redraft": _adp(row, "adp_2qb"),
            "dynasty_slp": _adp(row, "adp_dynasty_2qb"),
            "fp": NO_ADP,
            "sources": [],
        }

    # FantasyPros names -> Sleeper IDs, reusing the rankings matcher against
    # just the players Sleeper actually projects (no full players dump needed).
    index = SleeperPlayerIndex(
        SimpleNamespace(player_id=pid, full_name=v["name"], position=v["position"], team=v["team"])
        for pid, v in vets.items()
    )
    for ranked in fp_dynasty:
        result = match_player(ranked, index, {})
        if result.sleeper_player_id and result.sleeper_player_id in vets:
            vets[result.sleeper_player_id]["fp"] = float(ranked.rank_ecr)

    raw_dynasty: dict[str, float] = {}
    raw_redraft: dict[str, float] = {}
    raw_2027: dict[str, float] = {}
    for pid, v in vets.items():
        dyn_sources = [x for x in (v["dynasty_slp"], v["fp"]) if x < NO_ADP]
        dynasty = sum(dyn_sources) / len(dyn_sources) if dyn_sources else NO_ADP
        redraft = v["redraft"]
        if dynasty >= NO_ADP and redraft >= NO_ADP:
            continue  # nobody drafts this player in any format
        if v["dynasty_slp"] < NO_ADP:
            v["sources"].append("sleeper_dynasty_2qb")
        if v["fp"] < NO_ADP:
            v["sources"].append("fantasypros_dynasty_sf")
        if redraft < NO_ADP:
            v["sources"].append("sleeper_redraft_2qb")

        if dynasty < NO_ADP and redraft < NO_ADP:
            proj = REDRAFT_WEIGHT_2027 * redraft + (1 - REDRAFT_WEIGHT_2027) * dynasty
        elif dynasty < NO_ADP:
            proj = dynasty
        else:
            proj = redraft * REDRAFT_ONLY_PENALTY
        raw_2027[pid] = proj
        # A missing format sorts after everyone that has it, but keeps its
        # relative order via the other format.
        raw_dynasty[pid] = dynasty if dynasty < NO_ADP else 600 + redraft
        raw_redraft[pid] = redraft if redraft < NO_ADP else 600 + dynasty

    rookie_meta: dict[str, dict] = {}
    if include_rookies:
        for i, r in enumerate(rookies):
            rank = int(r.get("rank") or i + 1)
            pid = rookie_player_id(r["name"])
            rookie_meta[pid] = r
            for mode, raw in (("2027", raw_2027), ("dynasty", raw_dynasty), ("redraft", raw_redraft)):
                offset, spacing = ROOKIE_CURVES[mode]
                # +0.5 so a rookie and a veteran never tie at exactly the same value.
                curve = offset + spacing * (rank - 1) + 0.5
                raw[pid] = float(r["adp"]) if mode == "2027" and r.get("adp") else curve

    adp_2027 = _ordinal(raw_2027)
    adp_dynasty = _ordinal(raw_dynasty)
    adp_redraft = _ordinal(raw_redraft)

    board: list[BoardPlayer] = []
    for pid in adp_2027:
        if pid in rookie_meta:
            r = rookie_meta[pid]
            board.append(
                BoardPlayer(
                    player_id=pid,
                    name=r["name"],
                    position=r["position"],
                    team=None,
                    college=r.get("college"),
                    is_rookie=True,
                    years_exp=None,
                    adp_2027=adp_2027[pid],
                    adp_dynasty=adp_dynasty[pid],
                    adp_redraft=adp_redraft[pid],
                    sources=["rookie_seed_2027"],
                )
            )
        else:
            v = vets[pid]
            board.append(
                BoardPlayer(
                    player_id=pid,
                    name=v["name"],
                    position=v["position"],
                    team=v["team"],
                    years_exp=v["years_exp"],
                    adp_2027=adp_2027[pid],
                    adp_dynasty=adp_dynasty[pid],
                    adp_redraft=adp_redraft[pid],
                    sources=v["sources"],
                )
            )
    board.sort(key=lambda b: b.adp_2027)
    return board


def pool_for_mode(board: list[BoardPlayer], mode: str, *, include_rookies: bool = True, size: int = 450) -> list[dict]:
    """The slice of the board a single draft snapshots: the top `size`
    players for that mode, plus every K/DEF on the board (they sit far down
    any overall ranking but every league that starts one needs them).
    Re-numbered so the pool's own ADP is contiguous."""
    rows = [b for b in board if include_rookies or not b.is_rookie]
    rows.sort(key=lambda b: b.adp_for(mode))
    top = rows[:size]
    top_ids = {b.player_id for b in top}
    extras = [b for b in rows if b.position in ("K", "DEF") and b.player_id not in top_ids]
    extras_by_pos: dict[str, list[BoardPlayer]] = {}
    for b in extras:
        extras_by_pos.setdefault(b.position, []).append(b)
    chosen = top + [b for pos in extras_by_pos.values() for b in pos[:32]]
    chosen.sort(key=lambda b: b.adp_for(mode))

    pos_counter: dict[str, int] = {}
    pool: list[dict] = []
    for i, b in enumerate(chosen, start=1):
        pos_counter[b.position] = pos_counter.get(b.position, 0) + 1
        pool.append(
            {
                "player_id": b.player_id,
                "name": b.name,
                "position": b.position,
                "team": b.team,
                "adp": float(i),
                "pos_rank": f"{b.position}{pos_counter[b.position]}",
                "is_rookie": b.is_rookie,
                "college": b.college,
                "years_exp": b.years_exp,
            }
        )
    return pool
