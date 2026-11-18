"""Mock draft simulator API.

Two kinds of identity here, on purpose:

- Creating a draft (and the ADP board admin routes) needs a signed-in
  account, like the rest of the app -- that's what stops anonymous visitors
  from spinning up rooms.
- Everything *inside* a draft uses a per-draft participant token
  (`X-Mock-Token`, or `?token=` on the websocket). Joining from an invite link
  only asks for a display name, so friends can draft without signing up.

Actions go through one REST endpoint (`POST /drafts/{id}/actions`) so errors
come back as normal HTTP responses; the websocket only pushes state.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Any, Literal

from fantasy_agent.config import settings as app_settings
from fantasy_agent.db.models import AccountRecord, MockAdpRecord, MockDraftRecord
from fantasy_agent.mock_draft import engine as eng
from fantasy_agent.mock_draft.adp import pool_for_mode
from fantasy_agent.mock_draft.sleeper_import import import_league
from fantasy_agent.mock_draft.store import board_built_at, ensure_board, load_board, refresh_board
from fantasy_agent.sleeper.client import SleeperAPIError, SleeperClient
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import jobs
from ..deps import get_current_account, get_db, require_access_code
from ..mock.rooms import MAX_CHAT, Room, add_system_chat, hash_token, new_invite_code, new_token, rooms
from ..mock.views import snapshot
from ..schemas import JobOut

router = APIRouter(prefix="/mock", tags=["mock-draft"])

MAX_PARTICIPANTS = 40
POOL_MIN_SIZE = 450


# -- request models ---------------------------------------------------------


class SettingsIn(BaseModel):
    num_teams: int = Field(default=12, ge=eng.MIN_TEAMS, le=eng.MAX_TEAMS)
    rounds: int = Field(default=16, ge=1, le=eng.MAX_ROUNDS)
    draft_type: Literal["snake", "linear", "3rr"] = "snake"
    roster_slots: dict[str, int] = Field(default_factory=lambda: dict(eng.DEFAULT_ROSTER_SLOTS))
    pick_seconds: int = Field(default=60, ge=0, le=600)
    cpu_pick_seconds: float = Field(default=1.5, ge=0, le=10)
    adp_mode: Literal["2027", "dynasty", "redraft"] = "2027"
    include_rookies: bool = True
    cpu_randomness: float = Field(default=1.0, ge=0, le=5)

    def to_engine(self) -> eng.DraftSettings:
        return eng.DraftSettings(**self.model_dump(), scoring="ppr", season="2027")


class CreateDraftIn(BaseModel):
    name: str = Field(default="2027 Mock Draft", min_length=1, max_length=60)
    host_name: str | None = Field(default=None, max_length=30)
    settings: SettingsIn = Field(default_factory=SettingsIn)


class CreateDraftOut(BaseModel):
    draft_id: str
    invite_code: str
    participant_id: str
    token: str


class JoinIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)


class DraftSummaryOut(BaseModel):
    draft_id: str
    name: str
    invite_code: str
    status: str
    num_teams: int
    open_seats: int
    teams: list[dict]


class KeeperIn(BaseModel):
    team_id: int
    player_id: str
    round: int


class ActionIn(BaseModel):
    """One draft action. `type` picks which of the optional fields apply."""

    type: Literal[
        # anyone in the draft
        "pick",
        "queue",
        "autopick",
        "chat",
        "claim_seat",
        "leave_seat",
        # host only
        "update_settings",
        "rename_team",
        "set_order",
        "randomize_order",
        "set_pick_owner",
        "set_keepers",
        "assign_seat",
        "kick",
        "import_sleeper",
        "start",
        "pause",
        "resume",
        "undo",
        "force_pick",
        "reset",
        "rename_draft",
    ]
    player_id: str | None = None
    player_ids: list[str] | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    text: str | None = Field(default=None, max_length=300)
    team_id: int | None = None
    team_ids: list[int] | None = None
    name: str | None = Field(default=None, max_length=60)
    participant_id: str | None = None
    settings: SettingsIn | None = None
    round: int | None = None
    original_team_id: int | None = None
    owner_team_id: int | None = None
    keepers: list[KeeperIn] | None = None
    league_id: str | None = Field(default=None, max_length=32)
    season: str | None = Field(default=None, max_length=4)


HOST_ACTIONS = {
    "update_settings",
    "rename_team",
    "set_order",
    "randomize_order",
    "set_pick_owner",
    "set_keepers",
    "assign_seat",
    "kick",
    "import_sleeper",
    "start",
    "pause",
    "resume",
    "undo",
    "force_pick",
    "reset",
    "rename_draft",
}


# -- helpers --------------------------------------------------------------


def _build_pool(s: eng.DraftSettings) -> list[dict]:
    """Snapshot the ADP pool for a draft. Runs in a worker thread with its
    own short sessions -- never the request's -- so building the board on a
    fresh database can't hold a write transaction open under the request."""
    with rooms.session_scope() as session:
        board = load_board(session)
    if not board:
        try:
            ensure_board(rooms.session_scope)
        except Exception as exc:  # noqa: BLE001 -- surfaced as a 502 with the reason
            raise HTTPException(status_code=502, detail=f"Couldn't build the ADP board: {exc}") from exc
        with rooms.session_scope() as session:
            board = load_board(session)
    size = max(POOL_MIN_SIZE, s.num_teams * s.rounds * 2)
    return pool_for_mode(board, s.adp_mode, include_rookies=s.include_rookies, size=size)


async def _room_or_404(draft_id: str) -> Room:
    room = await rooms.get(draft_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return room


def _participant(room: Room, token: str | None) -> eng.Participant:
    if token:
        h = hash_token(token)
        for p in room.state.participants:
            if p.token_hash == h:
                return p
    raise HTTPException(status_code=401, detail="Not a participant in this draft -- use the invite link to join.")


def _err(exc: eng.DraftError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _summary(room: Room) -> DraftSummaryOut:
    st = room.state
    by_pid = {p.participant_id: p.name for p in st.participants}
    return DraftSummaryOut(
        draft_id=st.draft_id,
        name=st.name,
        invite_code=room.invite_code,
        status=st.status,
        num_teams=len(st.teams),
        open_seats=sum(1 for t in st.teams if t.participant_id is None),
        teams=[{"team_id": t.team_id, "name": t.name, "claimed_by": by_pid.get(t.participant_id)} for t in st.teams],
    )


# -- ADP board -----------------------------------------------------------


@router.get("/adp", dependencies=[Depends(get_current_account)])
def get_adp(
    mode: Literal["2027", "dynasty", "redraft"] = "2027",
    position: str | None = None,
    search: str | None = None,
    rookies_only: bool = False,
    limit: int = Query(default=300, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(MockAdpRecord)
    if position:
        q = q.filter(MockAdpRecord.position == position.upper())
    if rookies_only:
        q = q.filter(MockAdpRecord.is_rookie.is_(True))
    col = {"2027": MockAdpRecord.adp_2027, "dynasty": MockAdpRecord.adp_dynasty, "redraft": MockAdpRecord.adp_redraft}[mode]
    rows = q.order_by(col).all()
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in r.name.lower()]
    built = board_built_at(db)
    return {
        "built_at": built.isoformat() if built else None,
        "mode": mode,
        "players": [
            {
                "player_id": r.player_id,
                "name": r.name,
                "position": r.position,
                "team": r.team,
                "college": r.college,
                "is_rookie": bool(r.is_rookie),
                "adp": {"2027": r.adp_2027, "dynasty": r.adp_dynasty, "redraft": r.adp_redraft}[mode],
                "sources": r.sources,
            }
            for r in rows[:limit]
        ],
    }


@router.post(
    "/adp/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobOut,
    dependencies=[Depends(get_current_account), Depends(require_access_code)],
)
def refresh_adp(background: BackgroundTasks) -> JobOut:
    if jobs.is_kind_running("mock_adp"):
        raise HTTPException(status_code=409, detail="An ADP refresh is already running.")
    job = jobs.create_job("mock_adp")

    def _run() -> None:
        from fantasy_agent.db.session import get_session

        with get_session() as session:
            refresh_board(session)

    background.add_task(jobs.run_job, job.job_id, _run)
    return JobOut.model_validate(job)


# -- draft lifecycle -------------------------------------------------------


@router.post("/drafts", status_code=status.HTTP_201_CREATED, response_model=CreateDraftOut)
async def create_draft(
    body: CreateDraftIn,
    account: AccountRecord = Depends(get_current_account),
) -> CreateDraftOut:
    draft_settings = body.settings.to_engine()
    try:
        draft_settings.validate()
    except eng.DraftError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    pool = await asyncio.to_thread(_build_pool, draft_settings)

    token = new_token()
    host = eng.Participant(
        participant_id=uuid.uuid4().hex[:12],
        name=(body.host_name or account.display_name or account.email.split("@")[0])[:30],
        token_hash=hash_token(token),
        is_host=True,
        account_id=account.id,
    )
    state = eng.new_draft(uuid.uuid4().hex, body.name, draft_settings, host=host, now=rooms.clock())
    room = Room(
        draft_id=state.draft_id,
        invite_code=new_invite_code(),
        host_account_id=account.id,
        state=state,
        pool=pool,
    )
    await rooms.create(room)
    return CreateDraftOut(
        draft_id=state.draft_id, invite_code=room.invite_code, participant_id=host.participant_id, token=token
    )


@router.get("/drafts", response_model=list[DraftSummaryOut])
def my_drafts(account: AccountRecord = Depends(get_current_account), db: Session = Depends(get_db)) -> list:
    recs = (
        db.query(MockDraftRecord)
        .filter_by(host_account_id=account.id)
        .order_by(MockDraftRecord.updated_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for rec in recs:
        st = eng.DraftState.from_dict(rec.state)
        out.append(
            DraftSummaryOut(
                draft_id=rec.draft_id,
                name=rec.name,
                invite_code=rec.invite_code,
                status=st.status,
                num_teams=len(st.teams),
                open_seats=sum(1 for t in st.teams if t.participant_id is None),
                teams=[],
            )
        )
    return out


@router.post("/drafts/{draft_id}/host-token", response_model=CreateDraftOut)
async def reclaim_host(draft_id: str, account: AccountRecord = Depends(get_current_account)) -> CreateDraftOut:
    """A host on a new device/browser gets back in by being signed in --
    issues a fresh token for their host seat (the old one stops working)."""
    room = await _room_or_404(draft_id)
    if room.host_account_id != account.id:
        raise HTTPException(status_code=403, detail="Only the host's account can do that.")
    token = new_token()

    def _rotate(r: Room) -> str:
        host = next(p for p in r.state.participants if p.is_host)
        host.token_hash = hash_token(token)
        return host.participant_id

    pid = await rooms.mutate(room, _rotate)
    return CreateDraftOut(draft_id=draft_id, invite_code=room.invite_code, participant_id=str(pid), token=token)


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(draft_id: str, x_mock_token: str | None = Header(default=None)) -> None:
    room = await _room_or_404(draft_id)
    if not _participant(room, x_mock_token).is_host:
        raise HTTPException(status_code=403, detail="Only the host can delete the draft.")
    await rooms.delete(room)


@router.get("/invite/{code}", response_model=DraftSummaryOut)
async def invite_info(code: str) -> DraftSummaryOut:
    room = await rooms.get_by_invite(code)
    if room is None:
        raise HTTPException(status_code=404, detail="That invite link isn't valid.")
    return _summary(room)


@router.post("/invite/{code}/join", response_model=CreateDraftOut)
async def join(code: str, body: JoinIn) -> CreateDraftOut:
    room = await rooms.get_by_invite(code)
    if room is None:
        raise HTTPException(status_code=404, detail="That invite link isn't valid.")
    if len(room.state.participants) >= MAX_PARTICIPANTS:
        raise HTTPException(status_code=409, detail="This draft is full.")
    token = new_token()
    participant = eng.Participant(
        participant_id=uuid.uuid4().hex[:12], name=body.name.strip()[:30], token_hash=hash_token(token)
    )

    def _join(r: Room) -> None:
        st = r.state
        st.participants.append(participant)
        # Take the first open seat if there is one; otherwise watch.
        open_team = next((t for t in st.teams if t.participant_id is None), None)
        if open_team is not None and st.status != "complete":
            open_team.participant_id = participant.participant_id
            open_team.autopick = False
            if open_team.name.startswith("Team "):
                open_team.name = participant.name
            add_system_chat(st, f"{participant.name} joined and took {open_team.name}.", rooms.clock())
            eng.refresh_clock(st, now=rooms.clock())
        else:
            add_system_chat(st, f"{participant.name} joined as a spectator.", rooms.clock())

    await rooms.mutate(room, _join)
    return CreateDraftOut(
        draft_id=room.draft_id, invite_code=code, participant_id=participant.participant_id, token=token
    )


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str, x_mock_token: str | None = Header(default=None)) -> dict:
    room = await _room_or_404(draft_id)
    me = _participant(room, x_mock_token)
    return snapshot(room, me.participant_id, now=rooms.clock())


@router.get("/drafts/{draft_id}/pool")
async def get_pool(draft_id: str, x_mock_token: str | None = Header(default=None)) -> list[dict]:
    room = await _room_or_404(draft_id)
    _participant(room, x_mock_token)
    return room.pool


@router.get("/drafts/{draft_id}/export.csv")
async def export_csv(draft_id: str, token: str | None = None, x_mock_token: str | None = Header(default=None)):
    from fastapi.responses import PlainTextResponse

    room = await _room_or_404(draft_id)
    _participant(room, x_mock_token or token)
    st = room.state
    names = {t.team_id: t.name for t in st.teams}
    lines = ["overall,round,pick,team,original_team,player,position,nfl_team,adp,keeper"]

    def q(v: object) -> str:
        s = "" if v is None else str(v)
        return f'"{s.replace(chr(34), chr(34) * 2)}"' if any(c in s for c in ',"\n') else s

    for p in eng.preview_picks(st):
        pl = room.pool_by_id.get(p.player_id or "", {})
        lines.append(
            ",".join(
                q(v)
                for v in (
                    p.overall,
                    p.round,
                    f"{p.round}.{p.slot:02d}",
                    names.get(p.owner_team_id),
                    names.get(p.original_team_id) if p.original_team_id != p.owner_team_id else "",
                    pl.get("name"),
                    pl.get("position"),
                    pl.get("team") or pl.get("college"),
                    pl.get("adp"),
                    "yes" if p.is_keeper else "",
                )
            )
        )
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="mock-draft-{draft_id[:8]}.csv"'},
    )


# -- actions ---------------------------------------------------------------


@router.post("/drafts/{draft_id}/actions")
async def act(
    draft_id: str,
    action: ActionIn,
    x_mock_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    room = await _room_or_404(draft_id)
    me = _participant(room, x_mock_token)
    if action.type in HOST_ACTIONS and not me.is_host:
        raise HTTPException(status_code=403, detail="Only the host can do that.")

    # Anything that needs the DB or the network happens *before* taking the
    # room lock, so a slow Sleeper call never blocks picks.
    prepared: Any = None
    if action.type == "update_settings":
        if action.settings is None:
            raise HTTPException(status_code=422, detail="settings is required.")
        new_settings = action.settings.to_engine()
        old = room.state.settings
        if (new_settings.adp_mode, new_settings.include_rookies) != (old.adp_mode, old.include_rookies) or (
            new_settings.num_teams * new_settings.rounds * 2 > len(room.pool)
        ):
            prepared = await asyncio.to_thread(_build_pool, new_settings)
    elif action.type == "set_keepers":
        missing = [k.player_id for k in action.keepers or [] if k.player_id not in room.pool_by_id]
        if missing:
            rows = db.query(MockAdpRecord).filter(MockAdpRecord.player_id.in_(missing)).all()
            found = {r.player_id: r for r in rows}
            unknown = [m for m in missing if m not in found]
            if unknown:
                raise HTTPException(status_code=422, detail=f"Unknown player(s): {', '.join(unknown)}.")
            mode = room.state.settings.adp_mode
            prepared = [
                {
                    "player_id": r.player_id,
                    "name": r.name,
                    "position": r.position,
                    "team": r.team,
                    "adp": {"2027": r.adp_2027, "dynasty": r.adp_dynasty, "redraft": r.adp_redraft}[mode],
                    "pos_rank": None,
                    "is_rookie": bool(r.is_rookie),
                    "college": r.college,
                    "years_exp": r.years_exp,
                }
                for r in rows
            ]
    elif action.type == "import_sleeper":
        if not action.league_id:
            raise HTTPException(status_code=422, detail="league_id is required.")

        def _fetch():
            with SleeperClient(base_url=app_settings.sleeper_base_url) as client:
                return import_league(client, action.league_id, season=action.season or room.state.settings.season)

        try:
            prepared = await asyncio.to_thread(_fetch)
        except SleeperAPIError as exc:
            raise HTTPException(status_code=502, detail=f"Sleeper: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    elif action.type == "pick":
        if not action.player_id or action.player_id not in room.pool_by_id:
            raise HTTPException(status_code=422, detail="Unknown player.")

    def apply(r: Room) -> None:
        _apply_action(r, me, action, prepared)

    try:
        await rooms.mutate(room, apply)
    except eng.DraftError as exc:
        raise _err(exc) from exc
    return snapshot(room, me.participant_id, now=rooms.clock())


def _need(value: Any, field: str) -> Any:
    if value is None:
        raise eng.DraftError(f"{field} is required.")
    return value


def _apply_action(room: Room, me: eng.Participant, a: ActionIn, prepared: Any) -> None:
    st = room.state
    now = rooms.clock()
    my_team = st.team_for_participant(me.participant_id)

    match a.type:
        case "pick":
            pick = eng.current_pick(st)
            if pick is None:
                raise eng.DraftError("The draft isn't in progress.")
            if my_team is None or pick.owner_team_id != my_team.team_id:
                # The host can pick for anyone (e.g. drafting for a friend
                # who's offline) -- everyone else only on their own turn.
                if not me.is_host:
                    raise eng.DraftError("It's not your pick.")
            eng.make_pick(st, _need(a.player_id, "player_id"), now=now)
            if st.status == "complete":
                add_system_chat(st, "The draft is complete.", now)

        case "queue":
            ids = [pid for pid in _need(a.player_ids, "player_ids") if pid in room.pool_by_id]
            st.queues[me.participant_id] = list(dict.fromkeys(ids))

        case "autopick":
            if my_team is None:
                raise eng.DraftError("You don't have a team.")
            my_team.autopick = bool(a.enabled)
            eng.refresh_clock(st, now=now)

        case "chat":
            text = (a.text or "").strip()
            if not text:
                raise eng.DraftError("Message is empty.")
            st.chat.append(eng.ChatMessage(participant_id=me.participant_id, name=me.name, text=text, ts=now))
            del st.chat[:-MAX_CHAT]

        case "claim_seat":
            if st.status == "complete":
                raise eng.DraftError("The draft is over.")
            team = st.team(_need(a.team_id, "team_id"))
            if team.participant_id not in (None, me.participant_id):
                raise eng.DraftError("That team is taken.")
            if my_team is not None and my_team is not team:
                my_team.participant_id = None
                my_team.autopick = False
            team.participant_id = me.participant_id
            team.autopick = False
            eng.refresh_clock(st, now=now)

        case "leave_seat":
            if my_team is not None:
                my_team.participant_id = None
                my_team.autopick = False
                eng.refresh_clock(st, now=now)

        case "update_settings":
            eng.update_settings(st, _need(a.settings, "settings").to_engine())
            if prepared is not None:
                room.pool = prepared
                room.reindex_pool()

        case "rename_team":
            eng.rename_team(st, _need(a.team_id, "team_id"), _need(a.name, "name"))

        case "rename_draft":
            name = _need(a.name, "name").strip()
            if not name:
                raise eng.DraftError("Name can't be empty.")
            st.name = name[:60]

        case "set_order":
            eng.set_team_order(st, _need(a.team_ids, "team_ids"))

        case "randomize_order":
            ids = [t.team_id for t in st.teams]
            room.rng.shuffle(ids)
            eng.set_team_order(st, ids)

        case "set_pick_owner":
            eng.set_pick_owner(
                st, _need(a.round, "round"), _need(a.original_team_id, "original_team_id"), a.owner_team_id
            )

        case "set_keepers":
            if prepared:
                room.pool.extend(prepared)
                room.pool.sort(key=lambda p: p["adp"])
                room.reindex_pool()
            eng.set_keepers(st, [eng.Keeper(**k.model_dump()) for k in a.keepers or []])

        case "assign_seat":
            team = st.team(_need(a.team_id, "team_id"))
            if a.participant_id is not None:
                if st.participant(a.participant_id) is None:
                    raise eng.DraftError("No such participant.")
                current = st.team_for_participant(a.participant_id)
                if current is not None:
                    current.participant_id = None
                    current.autopick = False
            team.participant_id = a.participant_id
            team.autopick = False
            eng.refresh_clock(st, now=now)

        case "kick":
            target = st.participant(_need(a.participant_id, "participant_id"))
            if target is None:
                raise eng.DraftError("No such participant.")
            if target.is_host:
                raise eng.DraftError("The host can't be removed.")
            team = st.team_for_participant(target.participant_id)
            if team is not None:
                team.participant_id = None
                team.autopick = False
            st.participants.remove(target)
            st.queues.pop(target.participant_id, None)
            add_system_chat(st, f"{target.name} was removed by the host.", now)
            eng.refresh_clock(st, now=now)
            for ws, pid in list(room.sockets.items()):
                if pid == target.participant_id:
                    room.sockets.pop(ws, None)
                    asyncio.get_running_loop().create_task(ws.close(code=4403, reason="Removed by host"))

        case "import_sleeper":
            imp = prepared
            eng.replace_teams(
                st,
                [(t.team_id, t.name) for t in imp.teams],
                traded_picks=imp.traded_picks,
                rounds=imp.rounds,
                roster_slots=imp.roster_slots,
            )
            msg = f"Imported {imp.league_name}: {len(imp.teams)} teams, {len(imp.traded_picks)} traded {imp.season} picks."
            add_system_chat(st, " ".join([msg, *imp.notes]), now)

        case "start":
            eng.start(st, now=now)
            add_system_chat(st, "The draft has started. Good luck!", now)

        case "pause":
            eng.pause(st, now=now)
            add_system_chat(st, "The host paused the draft.", now)

        case "resume":
            eng.resume(st, now=now)
            add_system_chat(st, "The draft has resumed.", now)

        case "undo":
            undone = eng.undo_last_pick(st, now=now)
            add_system_chat(st, f"The host undid pick {undone.round}.{undone.slot:02d}.", now)

        case "force_pick":
            # Host makes the CPU pick right now for whoever's on the clock.
            pick = eng.current_pick(st)
            if pick is None or st.status != "drafting":
                raise eng.DraftError("The draft isn't running.")
            from fantasy_agent.mock_draft.cpu import autopick

            team = st.team(pick.owner_team_id)
            pid = autopick(
                st,
                team.team_id,
                room.available(),
                position_of=room.position_of,
                queue=st.queues.get(team.participant_id or ""),
                rng=room.rng,
            )
            if pid is None:
                raise eng.DraftError("No players left.")
            eng.make_pick(st, pid, now=now, auto=True)

        case "reset":
            st.status = "lobby"
            st.picks = []
            st.deadline = None
            st.paused_remaining = None
            st.started_at = None
            st.completed_at = None
            for t in st.teams:
                t.autopick = False
            add_system_chat(st, "The host reset the draft.", now)


# -- websocket -------------------------------------------------------------


@router.websocket("/drafts/{draft_id}/ws")
async def draft_socket(websocket: WebSocket, draft_id: str, token: Annotated[str | None, Query()] = None) -> None:
    room = await rooms.get(draft_id)
    if room is None:
        await websocket.close(code=4404, reason="Draft not found")
        return
    h = hash_token(token) if token else None
    me = next((p for p in room.state.participants if p.token_hash == h), None) if h else None
    if me is None:
        await websocket.close(code=4401, reason="Not a participant")
        return

    await websocket.accept()
    room.sockets[websocket] = me.participant_id
    # Everyone's presence dots change when someone connects.
    await rooms.broadcast(room)
    try:
        while True:
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong", "server_time": rooms.clock()})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        room.sockets.pop(websocket, None)
        await rooms.broadcast(room)
        rooms.evict_if_idle(room)
