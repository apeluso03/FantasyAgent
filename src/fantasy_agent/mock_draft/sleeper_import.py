"""Pre-fill a mock draft from a real Sleeper league: team names, roster
settings, and -- the main point -- every traded pick for the mock's season.

Sleeper lets leagues trade future picks, and its traded_picks endpoint
identifies each one the same way the mock engine does: (season, round,
original roster_id) -> current owner roster_id. So the mock uses Sleeper's
roster_id as its team_id directly and the ownership map copies across 1:1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..sleeper.client import SleeperAPIError, SleeperClient
from .engine import DEFAULT_ROSTER_SLOTS, MAX_ROUNDS, MAX_TEAMS

_SLOT_MAP = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "DEF": "DEF",
    "FLEX": "FLEX",
    "WRRB_FLEX": "FLEX",
    "REC_FLEX": "FLEX",
    "SUPER_FLEX": "SUPER_FLEX",
    "BN": "BN",
}
_IGNORED = {"IR", "TAXI"}


@dataclass
class ImportedTeam:
    team_id: int  # Sleeper roster_id
    name: str


@dataclass
class LeagueImport:
    league_id: str
    league_name: str
    season: str
    num_teams: int
    rounds: int
    roster_slots: dict[str, int]
    teams: list[ImportedTeam]
    # (round, original team_id, owner team_id)
    traded_picks: list[tuple[int, int, int]]
    notes: list[str] = field(default_factory=list)


def roster_slots_from_positions(roster_positions: list[str]) -> tuple[dict[str, int], list[str]]:
    slots = {k: 0 for k in DEFAULT_ROSTER_SLOTS}
    skipped: set[str] = set()
    for pos in roster_positions:
        if pos in _SLOT_MAP:
            slots[_SLOT_MAP[pos]] += 1
        elif pos not in _IGNORED:
            skipped.add(pos)
    notes = [f"Ignored roster slot(s) the mock doesn't model: {', '.join(sorted(skipped))}."] if skipped else []
    return slots, notes


def _draft_rounds(client: SleeperClient, league_id: str, league_settings: dict, slots: dict[str, int]) -> int:
    """How many rounds the league's draft really has.

    The league's own `draft_rounds` setting is unreliable -- in keeper
    leagues it can hold something else entirely (a real league reported 3
    while its actual drafts were 15 rounds). So, in order: the most recent
    real draft's round count, then the roster size (one pick per roster
    spot, IR/taxi excluded), and only then `draft_rounds`.
    """
    try:
        drafts = client.get_league_drafts(league_id)
    except SleeperAPIError:
        drafts = []
    for d in sorted(drafts, key=lambda d: (str(d.season or ""), d.draft_id), reverse=True):
        r = (d.settings or {}).get("rounds")
        if isinstance(r, int) and r > 0:
            return r
    roster_size = sum(slots.values())
    if roster_size:
        return roster_size
    return int(league_settings.get("draft_rounds") or 16)


def import_league(client: SleeperClient, league_id: str, *, season: str = "2027") -> LeagueImport:
    league = client.get_league(league_id)
    users = {u.user_id: u for u in client.get_users(league_id)}
    rosters = sorted(client.get_rosters(league_id), key=lambda r: r.roster_id)
    notes: list[str] = []

    if len(rosters) > MAX_TEAMS:
        raise ValueError(f"League has {len(rosters)} teams; the mock supports up to {MAX_TEAMS}.")

    teams = []
    for r in rosters:
        user = users.get(r.owner_id or "")
        name = user.team_name if user else f"Team {r.roster_id}"
        teams.append(ImportedTeam(team_id=r.roster_id, name=name[:40]))

    slots, slot_notes = roster_slots_from_positions(league.roster_positions)
    notes.extend(slot_notes)
    rounds = _draft_rounds(client, league_id, league.settings, slots)

    valid_ids = {t.team_id for t in teams}
    traded: list[tuple[int, int, int]] = []
    for tp in client.get_traded_picks(league_id):
        if str(tp.get("season")) != str(season):
            continue
        rnd, original, owner = int(tp["round"]), int(tp["roster_id"]), int(tp["owner_id"])
        if original == owner:
            continue  # traded away and back again
        if original not in valid_ids or owner not in valid_ids:
            notes.append(f"Skipped a round-{rnd} pick referencing an unknown roster.")
            continue
        traded.append((rnd, original, owner))

    # Every traded pick must land in the mock -- if one is in a round past
    # the detected length, the draft grows to include it rather than dropping it.
    deepest = max((rnd for rnd, _, _ in traded), default=0)
    if deepest > rounds:
        notes.append(f"Extended the draft from {rounds} to {deepest} rounds to include every traded pick.")
        rounds = deepest
    rounds = min(rounds, MAX_ROUNDS)

    # A future season's draft order isn't set until that season's draft
    # exists, so teams start in roster order -- the host sets the real order
    # (or randomizes) in the lobby.
    if not traded:
        notes.append(f"No traded {season} picks found in this league.")

    return LeagueImport(
        league_id=league_id,
        league_name=league.name,
        season=season,
        num_teams=len(teams),
        rounds=rounds,
        roster_slots=slots,
        teams=teams,
        traded_picks=sorted(traded),
        notes=notes,
    )
