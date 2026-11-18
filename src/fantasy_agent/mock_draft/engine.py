"""Mock draft state machine: pick order, traded-pick ownership, keepers.

Pure Python, no I/O, no clock reads (callers pass `now`) -- the web backend
owns persistence, websockets and timers, and this module owns the rules, the
same split the rest of the domain layer has with the CLI and the API.

Identity model, which is what makes traded picks work:

- A team's `team_id` is stable for the life of the draft. The draft order is
  just the order of `DraftState.teams`, so reordering teams moves their
  *original* picks with them.
- A pick is identified by (round, original_team_id) -- "Team 3's 2nd" -- the
  same way Sleeper's traded_picks endpoint identifies one. Its slot in the
  round comes from where the original team sits in the draft order.
- `pick_ownership` maps "round:original_team_id" to whoever owns it now. A
  missing key means the original team still owns it; `None` means the pick
  was removed from the draft entirely (forfeited, or traded out of a league
  the mock doesn't model).

So "Team 5 traded for Team 2's and Team 9's 2nd-rounders" is two ownership
entries, and both picks then show up in Team 5's column at Team 2's and
Team 9's slots, and disappear from Teams 2 and 9.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

DraftType = Literal["snake", "linear", "3rr"]
DraftStatus = Literal["lobby", "drafting", "paused", "complete"]
AdpMode = Literal["2027", "dynasty", "redraft"]

POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DEF")
FLEX_ELIGIBLE = frozenset({"RB", "WR", "TE"})
SUPER_FLEX_ELIGIBLE = frozenset({"QB", "RB", "WR", "TE"})
SLOT_NAMES: tuple[str, ...] = ("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "BN")

MAX_TEAMS = 12
MIN_TEAMS = 2
MAX_ROUNDS = 30

# Superflex PPR, 1 QB / 2 RB / 3 WR / 1 TE / 1 FLEX / 1 SUPER_FLEX / 1 K, no
# DEF -- the requested default. Six bench spots makes 16 rounds.
DEFAULT_ROSTER_SLOTS: dict[str, int] = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
    "FLEX": 1,
    "SUPER_FLEX": 1,
    "K": 1,
    "DEF": 0,
    "BN": 6,
}


class DraftError(ValueError):
    """A rule violation the caller should show the user (wrong turn, player
    already taken, editing settings mid-draft, ...)."""


@dataclass
class DraftSettings:
    num_teams: int = 12
    rounds: int = 16
    draft_type: DraftType = "snake"
    roster_slots: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_ROSTER_SLOTS))
    scoring: str = "ppr"
    # Seconds per human pick; 0 means untimed (pick whenever).
    pick_seconds: int = 60
    # How long a CPU "thinks" before picking, so the board doesn't jump ahead
    # faster than people can follow.
    cpu_pick_seconds: float = 1.5
    adp_mode: AdpMode = "2027"
    include_rookies: bool = True
    # 0 = CPUs always take the best fit by ADP; higher = more variance, so
    # repeated mocks don't all play out the same way.
    cpu_randomness: float = 1.0
    season: str = "2027"

    def validate(self) -> None:
        if not MIN_TEAMS <= self.num_teams <= MAX_TEAMS:
            raise DraftError(f"Teams must be between {MIN_TEAMS} and {MAX_TEAMS}.")
        if not 1 <= self.rounds <= MAX_ROUNDS:
            raise DraftError(f"Rounds must be between 1 and {MAX_ROUNDS}.")
        if self.draft_type not in ("snake", "linear", "3rr"):
            raise DraftError("Draft type must be snake, linear, or 3rr.")
        if self.adp_mode not in ("2027", "dynasty", "redraft"):
            raise DraftError("ADP mode must be 2027, dynasty, or redraft.")
        unknown = set(self.roster_slots) - set(SLOT_NAMES)
        if unknown:
            raise DraftError(f"Unknown roster slot(s): {', '.join(sorted(unknown))}.")
        if any(v < 0 or v > 10 for v in self.roster_slots.values()):
            raise DraftError("Each roster slot count must be between 0 and 10.")
        if self.pick_seconds < 0 or self.pick_seconds > 600:
            raise DraftError("Pick timer must be between 0 (untimed) and 600 seconds.")

    @property
    def starter_slot_count(self) -> int:
        return sum(v for k, v in self.roster_slots.items() if k != "BN")


@dataclass
class Team:
    team_id: int
    name: str
    participant_id: str | None = None
    # A seated human can flip this on (Sleeper's "autopick" toggle); an
    # unseated team is always CPU-drafted regardless.
    autopick: bool = False


@dataclass
class Participant:
    participant_id: str
    name: str
    token_hash: str
    is_host: bool = False
    account_id: int | None = None


@dataclass
class Keeper:
    team_id: int
    player_id: str
    round: int


@dataclass
class Pick:
    overall: int
    round: int
    slot: int  # 1-based position within the round
    original_team_id: int
    owner_team_id: int
    player_id: str | None = None
    is_keeper: bool = False
    auto: bool = False  # made by CPU/autopick/timeout rather than a person
    picked_at: float | None = None

    @property
    def is_traded(self) -> bool:
        return self.owner_team_id != self.original_team_id

    @property
    def label(self) -> str:
        return f"{self.round}.{self.slot:02d}"


@dataclass
class ChatMessage:
    participant_id: str | None  # None for system messages
    name: str
    text: str
    ts: float


@dataclass
class DraftState:
    draft_id: str
    name: str
    settings: DraftSettings
    teams: list[Team]
    participants: list[Participant] = field(default_factory=list)
    status: DraftStatus = "lobby"
    pick_ownership: dict[str, int | None] = field(default_factory=dict)
    keepers: list[Keeper] = field(default_factory=list)
    picks: list[Pick] = field(default_factory=list)
    # Wall-clock deadline for the pick on the clock (None when untimed or not drafting).
    deadline: float | None = None
    # Seconds left on the clock when the host paused, restored on resume.
    paused_remaining: float | None = None
    queues: dict[str, list[str]] = field(default_factory=dict)
    chat: list[ChatMessage] = field(default_factory=list)
    created_at: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    # Bumped on every mutation; lets clients drop out-of-order snapshots.
    version: int = 0

    # -- serialization -------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DraftState":
        data = dict(data)
        settings = DraftSettings(**data.pop("settings"))
        return cls(
            settings=settings,
            teams=[Team(**t) for t in data.pop("teams")],
            participants=[Participant(**p) for p in data.pop("participants", [])],
            keepers=[Keeper(**k) for k in data.pop("keepers", [])],
            picks=[Pick(**p) for p in data.pop("picks", [])],
            chat=[ChatMessage(**c) for c in data.pop("chat", [])],
            # JSON round-trips turn None-valued dict entries fine, but keys are always str already.
            pick_ownership=dict(data.pop("pick_ownership", {})),
            **data,
        )

    # -- lookups ---------------------------------------------------------

    def team(self, team_id: int) -> Team:
        for t in self.teams:
            if t.team_id == team_id:
                return t
        raise DraftError(f"No team {team_id} in this draft.")

    def participant(self, participant_id: str) -> Participant | None:
        return next((p for p in self.participants if p.participant_id == participant_id), None)

    def team_for_participant(self, participant_id: str) -> Team | None:
        return next((t for t in self.teams if t.participant_id == participant_id), None)


def ownership_key(round_no: int, original_team_id: int) -> str:
    return f"{round_no}:{original_team_id}"


# -- construction / lobby edits ------------------------------------------


def new_draft(
    draft_id: str,
    name: str,
    settings: DraftSettings,
    *,
    host: Participant,
    now: float,
) -> DraftState:
    settings.validate()
    teams = [Team(team_id=i, name=f"Team {i}") for i in range(1, settings.num_teams + 1)]
    teams[0].participant_id = host.participant_id
    teams[0].name = host.name
    return DraftState(
        draft_id=draft_id,
        name=name,
        settings=settings,
        teams=teams,
        participants=[host],
        created_at=now,
    )


def _require_lobby(state: DraftState) -> None:
    if state.status != "lobby":
        raise DraftError("That can only be changed before the draft starts.")


def update_settings(state: DraftState, new: DraftSettings) -> None:
    _require_lobby(state)
    new.validate()
    old_n = state.settings.num_teams
    state.settings = new
    if new.num_teams > old_n:
        next_id = max(t.team_id for t in state.teams) + 1
        for i in range(new.num_teams - old_n):
            state.teams.append(Team(team_id=next_id + i, name=f"Team {len(state.teams) + 1}"))
    elif new.num_teams < old_n:
        removed = state.teams[new.num_teams :]
        if any(t.participant_id for t in removed):
            # Drop from the end, but never silently unseat a person -- move
            # the CPU teams out instead where possible.
            cpu = [t for t in state.teams if not t.participant_id]
            humans = [t for t in state.teams if t.participant_id]
            if len(humans) > new.num_teams:
                raise DraftError("More people are seated than that many teams -- remove someone first.")
            keep_cpu = new.num_teams - len(humans)
            kept_ids = {t.team_id for t in humans} | {t.team_id for t in cpu[:keep_cpu]}
            state.teams = [t for t in state.teams if t.team_id in kept_ids]
        else:
            state.teams = state.teams[: new.num_teams]
        _prune_team_references(state)
    _prune_rounds(state)


def _prune_team_references(state: DraftState) -> None:
    ids = {t.team_id for t in state.teams}
    state.pick_ownership = {
        k: v
        for k, v in state.pick_ownership.items()
        if int(k.split(":")[1]) in ids and (v is None or v in ids)
    }
    state.keepers = [k for k in state.keepers if k.team_id in ids]


def _prune_rounds(state: DraftState) -> None:
    r = state.settings.rounds
    state.pick_ownership = {k: v for k, v in state.pick_ownership.items() if int(k.split(":")[0]) <= r}
    state.keepers = [k for k in state.keepers if k.round <= r]


def set_team_order(state: DraftState, team_ids: list[int]) -> None:
    _require_lobby(state)
    if sorted(team_ids) != sorted(t.team_id for t in state.teams):
        raise DraftError("Draft order must list every team exactly once.")
    by_id = {t.team_id: t for t in state.teams}
    state.teams = [by_id[i] for i in team_ids]


def rename_team(state: DraftState, team_id: int, name: str) -> None:
    name = name.strip()
    if not name or len(name) > 40:
        raise DraftError("Team names must be 1-40 characters.")
    state.team(team_id).name = name


def set_pick_owner(state: DraftState, round_no: int, original_team_id: int, owner_team_id: int | None) -> None:
    """Trade (or remove) one pick. Before the draft this edits the ownership
    map; during it, only a pick that hasn't been made yet can move, and it
    can't be removed outright (that would renumber picks people can see)."""
    if not 1 <= round_no <= state.settings.rounds:
        raise DraftError(f"Round must be between 1 and {state.settings.rounds}.")
    state.team(original_team_id)
    if owner_team_id is not None:
        state.team(owner_team_id)

    key = ownership_key(round_no, original_team_id)
    if state.status == "lobby":
        if owner_team_id == original_team_id:
            state.pick_ownership.pop(key, None)
        else:
            state.pick_ownership[key] = owner_team_id
        return

    if state.status == "complete":
        raise DraftError("The draft is over.")
    if owner_team_id is None:
        raise DraftError("Picks can only be removed before the draft starts.")
    pick = next(
        (p for p in state.picks if p.round == round_no and p.original_team_id == original_team_id),
        None,
    )
    if pick is None:
        raise DraftError("That pick isn't in this draft.")
    if pick.player_id is not None:
        raise DraftError("That pick has already been made.")
    pick.owner_team_id = owner_team_id
    if owner_team_id == original_team_id:
        state.pick_ownership.pop(key, None)
    else:
        state.pick_ownership[key] = owner_team_id


def set_keepers(state: DraftState, keepers: list[Keeper]) -> None:
    _require_lobby(state)
    seen: set[str] = set()
    for k in keepers:
        state.team(k.team_id)
        if not 1 <= k.round <= state.settings.rounds:
            raise DraftError(f"Keeper round must be between 1 and {state.settings.rounds}.")
        if k.player_id in seen:
            raise DraftError("A player can only be kept once.")
        seen.add(k.player_id)
    state.keepers = list(keepers)


# -- pick order ------------------------------------------------------------


def round_is_reversed(draft_type: DraftType, round_no: int) -> bool:
    if draft_type == "linear":
        return False
    if draft_type == "snake":
        return round_no % 2 == 0
    # Third-round reversal (Sleeper's 3RR): 1 forward, 2 and 3 reversed,
    # then alternating again -- so from round 3 on, odd rounds reverse.
    if round_no == 1:
        return False
    if round_no == 2:
        return True
    return round_no % 2 == 1


def build_picks(state: DraftState) -> list[Pick]:
    """Every pick in draft order with current ownership applied (keepers not
    yet placed). Removed picks are skipped, so `overall` stays contiguous."""
    order = [t.team_id for t in state.teams]
    picks: list[Pick] = []
    overall = 0
    for rnd in range(1, state.settings.rounds + 1):
        seq = list(reversed(order)) if round_is_reversed(state.settings.draft_type, rnd) else order
        for slot_idx, original in enumerate(seq, start=1):
            key = ownership_key(rnd, original)
            owner = state.pick_ownership.get(key, original) if key in state.pick_ownership else original
            if owner is None:
                continue
            overall += 1
            picks.append(
                Pick(overall=overall, round=rnd, slot=slot_idx, original_team_id=original, owner_team_id=owner)
            )
    return picks


def place_keepers(picks: list[Pick], keepers: list[Keeper]) -> list[str]:
    """Fill each keeper into the earliest pick its team owns in the keeper's
    round, in place. Returns problems (team owns no pick in that round)."""
    problems: list[str] = []
    for k in keepers:
        target = next(
            (
                p
                for p in picks
                if p.round == k.round and p.owner_team_id == k.team_id and p.player_id is None
            ),
            None,
        )
        if target is None:
            problems.append(f"Team {k.team_id} has no open round-{k.round} pick for keeper {k.player_id}.")
            continue
        target.player_id = k.player_id
        target.is_keeper = True
        target.auto = True
    return problems


def preview_picks(state: DraftState) -> list[Pick]:
    if state.status != "lobby":
        return state.picks
    picks = build_picks(state)
    place_keepers(picks, state.keepers)
    return picks


def validate_for_start(state: DraftState) -> list[str]:
    problems: list[str] = []
    picks = build_picks(state)
    problems.extend(place_keepers(picks, state.keepers))
    if all(p.player_id is not None for p in picks):
        problems.append("There are no open picks to make.")
    return problems


def start(state: DraftState, *, now: float) -> None:
    _require_lobby(state)
    problems = validate_for_start(state)
    if problems:
        raise DraftError(" ".join(problems))
    state.picks = build_picks(state)
    place_keepers(state.picks, state.keepers)
    state.status = "drafting"
    state.started_at = now
    _advance_clock(state, now)


def current_pick(state: DraftState) -> Pick | None:
    if state.status not in ("drafting", "paused"):
        return None
    return next((p for p in state.picks if p.player_id is None), None)


def drafted_ids(state: DraftState) -> set[str]:
    source = state.picks if state.status != "lobby" else preview_picks(state)
    return {p.player_id for p in source if p.player_id is not None}


def is_cpu_controlled(state: DraftState, team_id: int) -> bool:
    team = state.team(team_id)
    return team.participant_id is None or team.autopick


def _advance_clock(state: DraftState, now: float) -> None:
    nxt = current_pick(state)
    if nxt is None:
        state.status = "complete"
        state.completed_at = now
        state.deadline = None
        return
    if state.settings.pick_seconds and not is_cpu_controlled(state, nxt.owner_team_id):
        state.deadline = now + state.settings.pick_seconds
    else:
        state.deadline = None


def make_pick(state: DraftState, player_id: str, *, now: float, auto: bool = False) -> Pick:
    if state.status == "paused":
        raise DraftError("The draft is paused.")
    pick = current_pick(state)
    if pick is None:
        raise DraftError("The draft isn't in progress.")
    if player_id in drafted_ids(state):
        raise DraftError("That player has already been drafted.")
    pick.player_id = player_id
    pick.auto = auto
    pick.picked_at = now
    for queue in state.queues.values():
        if player_id in queue:
            queue.remove(player_id)
    _advance_clock(state, now)
    state.version += 1
    return pick


def undo_last_pick(state: DraftState, *, now: float) -> Pick:
    if state.status not in ("drafting", "paused", "complete"):
        raise DraftError("No picks to undo.")
    made = [p for p in state.picks if p.player_id is not None and not p.is_keeper]
    if not made:
        raise DraftError("No picks to undo.")
    last = max(made, key=lambda p: p.overall)
    last.player_id = None
    last.auto = False
    last.picked_at = None
    if state.status == "complete":
        state.status = "drafting"
        state.completed_at = None
    if state.status == "drafting":
        _advance_clock(state, now)
    else:
        state.paused_remaining = state.settings.pick_seconds or None
    state.version += 1
    return last


def pause(state: DraftState, *, now: float) -> None:
    if state.status != "drafting":
        raise DraftError("The draft isn't running.")
    state.status = "paused"
    state.paused_remaining = max(0.0, state.deadline - now) if state.deadline else None
    state.deadline = None


def resume(state: DraftState, *, now: float) -> None:
    if state.status != "paused":
        raise DraftError("The draft isn't paused.")
    state.status = "drafting"
    pick = current_pick(state)
    if pick and state.settings.pick_seconds and not is_cpu_controlled(state, pick.owner_team_id):
        # Never resume onto a clock that's about to fire before anyone can react.
        remaining = state.paused_remaining if state.paused_remaining is not None else state.settings.pick_seconds
        state.deadline = now + max(remaining, 10.0)
    else:
        state.deadline = None
    state.paused_remaining = None


def refresh_clock(state: DraftState, *, now: float) -> None:
    """Re-derive the deadline after something changed who controls the
    pick on the clock (a seat was claimed, autopick toggled)."""
    if state.status == "drafting":
        pick = current_pick(state)
        human_now = pick is not None and not is_cpu_controlled(state, pick.owner_team_id)
        if human_now and state.deadline is None and state.settings.pick_seconds:
            state.deadline = now + state.settings.pick_seconds
        elif not human_now:
            state.deadline = None


# -- roster views ----------------------------------------------------------


def team_player_ids(state: DraftState, team_id: int) -> list[str]:
    source = state.picks if state.status != "lobby" else preview_picks(state)
    return [p.player_id for p in sorted(source, key=lambda p: p.overall) if p.owner_team_id == team_id and p.player_id]


def unfilled_starters(position_counts: dict[str, int], roster_slots: dict[str, int]) -> dict[str, int]:
    """Starting slots a roster still can't fill, given how many players it
    has at each position. Fills dedicated slots first, then SUPER_FLEX with
    spare QBs (the only position that can't go to FLEX), then FLEX, then any
    SUPER_FLEX left with spare RB/WR/TE."""
    left = {pos: position_counts.get(pos, 0) for pos in POSITIONS}
    need: dict[str, int] = {}
    for pos in POSITIONS:
        n = roster_slots.get(pos, 0)
        used = min(n, left[pos])
        left[pos] -= used
        if n - used:
            need[pos] = n - used

    sf = roster_slots.get("SUPER_FLEX", 0)
    qb_to_sf = min(sf, left["QB"])
    left["QB"] -= qb_to_sf
    sf -= qb_to_sf

    flex = roster_slots.get("FLEX", 0)
    for pos in ("RB", "WR", "TE"):
        take = min(flex, left[pos])
        left[pos] -= take
        flex -= take
    for pos in ("RB", "WR", "TE"):
        take = min(sf, left[pos])
        left[pos] -= take
        sf -= take

    if flex:
        need["FLEX"] = flex
    if sf:
        need["SUPER_FLEX"] = sf
    return need


def assign_lineup(players: list[tuple[str, str]], roster_slots: dict[str, int]) -> list[tuple[str, str | None]]:
    """Slot a drafted roster, in draft order, into starters then bench.
    `players` is (player_id, position) best-first; returns (slot, player_id)
    with None for an empty starting slot."""
    remaining = list(players)
    out: list[tuple[str, str | None]] = []

    def take(eligible: frozenset[str] | set[str]) -> str | None:
        for i, (pid, pos) in enumerate(remaining):
            if pos in eligible:
                remaining.pop(i)
                return pid
        return None

    for slot in ("QB", "RB", "WR", "TE"):
        for _ in range(roster_slots.get(slot, 0)):
            out.append((slot, take({slot})))
    for _ in range(roster_slots.get("FLEX", 0)):
        out.append(("FLEX", take(FLEX_ELIGIBLE)))
    for _ in range(roster_slots.get("SUPER_FLEX", 0)):
        out.append(("SUPER_FLEX", take(SUPER_FLEX_ELIGIBLE)))
    for slot in ("K", "DEF"):
        for _ in range(roster_slots.get(slot, 0)):
            out.append((slot, take({slot})))
    out.extend(("BN", pid) for pid, _ in remaining)
    return out


def replace_teams(
    state: DraftState,
    teams: list[tuple[int, str]],
    *,
    traded_picks: list[tuple[int, int, int]],
    rounds: int | None = None,
    roster_slots: dict[str, int] | None = None,
) -> None:
    """Swap in an imported team list (e.g. a Sleeper league's rosters, with
    their roster_ids as team_ids) plus its traded picks. People already
    seated keep a seat at the same draft position."""
    _require_lobby(state)
    if not MIN_TEAMS <= len(teams) <= MAX_TEAMS:
        raise DraftError(f"Teams must be between {MIN_TEAMS} and {MAX_TEAMS}.")
    seats = [(t.participant_id, t.autopick) for t in state.teams]
    new_teams = [Team(team_id=tid, name=name[:40] or f"Team {tid}") for tid, name in teams]
    for team, (pid, auto) in zip(new_teams, seats):
        team.participant_id, team.autopick = pid, auto
    # Anyone who sat past the end of a now-shorter list goes to the first open seat.
    for pid, auto in seats[len(new_teams) :]:
        if pid is None:
            continue
        open_team = next((t for t in new_teams if t.participant_id is None), None)
        if open_team is not None:
            open_team.participant_id, open_team.autopick = pid, auto

    settings = DraftSettings(**asdict(state.settings))
    settings.num_teams = len(new_teams)
    if rounds is not None:
        settings.rounds = rounds
    if roster_slots is not None:
        settings.roster_slots = dict(roster_slots)
    settings.validate()

    state.settings = settings
    state.teams = new_teams
    state.keepers = []
    state.pick_ownership = {}
    for rnd, original, owner in traded_picks:
        set_pick_owner(state, rnd, original, owner)
