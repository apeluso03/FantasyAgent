"""Live mock draft rooms: in-memory state, websocket fan-out, and the clock.

One `Room` per draft that someone has touched since the server started. The
room holds the engine's DraftState (the source of truth while it's in
memory), persists it to `mock_drafts` after every change, and runs one
asyncio "driver" task that makes CPU picks and fires the pick clock.

This is deliberately single-process, same tradeoff as jobs.py: rooms live in
one server's memory, so the deployment must run exactly one worker/replica
(railway.json pins this). The DB copy means a restart resumes every draft
where it left off -- it just can't be shared across processes. Scaling out
would mean moving the room state and pub/sub to Redis.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import random
import secrets
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from fantasy_agent.db.models import MockDraftRecord
from fantasy_agent.db.session import get_session
from fantasy_agent.mock_draft import engine as eng
from fantasy_agent.mock_draft.cpu import PoolPlayer, autopick, choose_player
from fastapi import WebSocket
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

MAX_CHAT = 100


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(24)


def new_invite_code() -> str:
    # Short enough to read out loud, long enough not to be guessable.
    return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")


@dataclass
class Room:
    draft_id: str
    invite_code: str
    host_account_id: int | None
    state: eng.DraftState
    pool: list[dict]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sockets: dict[WebSocket, str] = field(default_factory=dict)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    driver: asyncio.Task | None = None
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        self.reindex_pool()

    def reindex_pool(self) -> None:
        self.pool_by_id = {p["player_id"]: p for p in self.pool}
        self.position_of = {p["player_id"]: p["position"] for p in self.pool}

    def available(self) -> list[PoolPlayer]:
        taken = eng.drafted_ids(self.state)
        return [
            PoolPlayer(p["player_id"], p["position"], float(p["adp"]))
            for p in self.pool
            if p["player_id"] not in taken
        ]

    def online_ids(self) -> set[str]:
        return set(self.sockets.values())


SessionScope = Callable[[], AbstractContextManager[Session]]


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._load_lock = asyncio.Lock()
        # Swappable so tests can point rooms at their in-memory database.
        self.session_scope: SessionScope = get_session
        # Lets tests opt out of real-time CPU delays.
        self.clock: Callable[[], float] = time.time

    # -- persistence -------------------------------------------------------

    def _save_sync(self, room: Room) -> None:
        with self.session_scope() as session:
            rec = session.get(MockDraftRecord, room.draft_id)
            if rec is None:
                rec = MockDraftRecord(
                    draft_id=room.draft_id,
                    invite_code=room.invite_code,
                    host_account_id=room.host_account_id,
                    name=room.state.name,
                )
                session.add(rec)
            rec.name = room.state.name
            rec.status = room.state.status
            rec.state = room.state.to_dict()
            rec.pool = room.pool

    async def save(self, room: Room) -> None:
        await asyncio.to_thread(self._save_sync, room)

    def _load_sync(self, *, draft_id: str | None = None, invite_code: str | None = None) -> Room | None:
        with self.session_scope() as session:
            if draft_id is not None:
                rec = session.get(MockDraftRecord, draft_id)
            else:
                rec = session.query(MockDraftRecord).filter_by(invite_code=invite_code).one_or_none()
            if rec is None:
                return None
            return Room(
                draft_id=rec.draft_id,
                invite_code=rec.invite_code,
                host_account_id=rec.host_account_id,
                state=eng.DraftState.from_dict(rec.state),
                pool=list(rec.pool or []),
            )

    async def get(self, draft_id: str) -> Room | None:
        room = self._rooms.get(draft_id)
        if room is not None:
            return room
        async with self._load_lock:
            room = self._rooms.get(draft_id)
            if room is None:
                room = await asyncio.to_thread(self._load_sync, draft_id=draft_id)
                if room is not None:
                    self._activate(room)
        return room

    async def get_by_invite(self, code: str) -> Room | None:
        for room in self._rooms.values():
            if room.invite_code == code:
                return room
        loaded = await asyncio.to_thread(self._load_sync, invite_code=code)
        return await self.get(loaded.draft_id) if loaded else None

    async def create(self, room: Room) -> Room:
        await self.save(room)
        self._activate(room)
        return room

    async def delete(self, room: Room) -> None:
        self._rooms.pop(room.draft_id, None)
        if room.driver:
            room.driver.cancel()
        for ws in list(room.sockets):
            with contextlib.suppress(Exception):
                await ws.close(code=4404, reason="Draft deleted")

        def _delete() -> None:
            with self.session_scope() as session:
                rec = session.get(MockDraftRecord, room.draft_id)
                if rec is not None:
                    session.delete(rec)

        await asyncio.to_thread(_delete)

    def _activate(self, room: Room) -> None:
        now = self.clock()
        st = room.state
        # Coming back from a restart: give whoever's on the clock a fresh
        # timer instead of instantly auto-picking for them.
        if st.status == "drafting" and st.deadline is not None and st.deadline < now:
            st.deadline = now + max(st.settings.pick_seconds, 15)
        self._rooms[room.draft_id] = room
        room.driver = asyncio.get_running_loop().create_task(self._drive(room))

    def evict_if_idle(self, room: Room) -> None:
        """Drop a room nobody is watching that has nothing left to drive.
        A draft in progress keeps running (CPUs and timeouts finish it)."""
        if not room.sockets and room.state.status in ("lobby", "complete", "paused"):
            if self._rooms.get(room.draft_id) is room:
                self._rooms.pop(room.draft_id, None)
                if room.driver:
                    room.driver.cancel()

    async def shutdown(self) -> None:
        for room in list(self._rooms.values()):
            if room.driver:
                room.driver.cancel()
        self._rooms.clear()

    # -- mutation + fan-out ----------------------------------------------

    async def mutate(self, room: Room, fn: Callable[[Room], object]) -> object:
        """Apply `fn` under the room lock, then persist, broadcast and poke
        the driver. `fn` raising DraftError leaves nothing half-applied
        worth saving (engine functions validate before they change state)."""
        async with room.lock:
            result = fn(room)
            room.state.version += 1
            await self.save(room)
        room.wake.set()
        await self.broadcast(room)
        return result

    async def broadcast(self, room: Room) -> None:
        from .views import snapshot  # local import: views imports this module's types

        dead: list[WebSocket] = []
        for ws, pid in list(room.sockets.items()):
            try:
                await ws.send_json({"type": "state", "state": snapshot(room, pid, now=self.clock())})
            except Exception:  # noqa: BLE001 -- a dropped socket shouldn't stop the others
                dead.append(ws)
        for ws in dead:
            room.sockets.pop(ws, None)

    # -- the driver ------------------------------------------------------

    async def _drive(self, room: Room) -> None:
        try:
            while True:
                room.wake.clear()
                st = room.state
                pick = eng.current_pick(st)
                if st.status != "drafting" or pick is None:
                    await room.wake.wait()
                    continue

                if eng.is_cpu_controlled(st, pick.owner_team_id):
                    delay: float | None = max(0.0, st.settings.cpu_pick_seconds)
                elif st.deadline is not None:
                    delay = max(0.0, st.deadline - self.clock())
                else:
                    delay = None  # untimed human pick: wait for them

                try:
                    await asyncio.wait_for(room.wake.wait(), timeout=delay)
                    continue  # something changed -- re-evaluate from scratch
                except asyncio.TimeoutError:
                    pass

                await self._auto_pick(room, expected_overall=pick.overall)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Mock draft driver crashed for %s", room.draft_id)

    async def _auto_pick(self, room: Room, *, expected_overall: int) -> None:
        async with room.lock:
            st = room.state
            pick = eng.current_pick(st)
            if st.status != "drafting" or pick is None or pick.overall != expected_overall:
                return  # someone picked (or paused) while we were waiting
            team = st.team(pick.owner_team_id)
            timed_out = not eng.is_cpu_controlled(st, team.team_id)
            available = room.available()
            if team.participant_id is not None:
                pid = autopick(
                    st,
                    team.team_id,
                    available,
                    position_of=room.position_of,
                    queue=st.queues.get(team.participant_id),
                    rng=room.rng,
                )
            else:
                pid = choose_player(st, team.team_id, available, position_of=room.position_of, rng=room.rng)
            if pid is None:
                return
            now = self.clock()
            if timed_out:
                # Like Sleeper: missing your clock turns autopick on, so an
                # absent drafter doesn't stall every one of their picks.
                team.autopick = True
                add_system_chat(st, f"{team.name} ran out of time -- autopick is now on.", now)
            eng.make_pick(st, pid, now=now, auto=True)
            if st.status == "complete":
                add_system_chat(st, "The draft is complete.", now)
            await self.save(room)
        await self.broadcast(room)


def add_system_chat(state: eng.DraftState, text: str, now: float) -> None:
    state.chat.append(eng.ChatMessage(participant_id=None, name="Draft", text=text, ts=now))
    del state.chat[:-MAX_CHAT]


rooms = RoomManager()
