"""What clients see: the JSON snapshot pushed over the websocket and
returned from every REST action. Token hashes never leave the server, and a
participant only ever sees their own queue."""

from __future__ import annotations

from dataclasses import asdict

from fantasy_agent.mock_draft import engine as eng

from .rooms import Room


def snapshot(room: Room, viewer_id: str | None, *, now: float) -> dict:
    st = room.state
    online = room.online_ids()
    by_pid = {p.participant_id: p for p in st.participants}
    viewer = by_pid.get(viewer_id) if viewer_id else None
    my_team = st.team_for_participant(viewer_id) if viewer_id else None
    picks = eng.preview_picks(st)
    current = eng.current_pick(st)

    return {
        "draft_id": st.draft_id,
        "name": st.name,
        "invite_code": room.invite_code,
        "status": st.status,
        "version": st.version,
        "settings": asdict(st.settings),
        "teams": [
            {
                "team_id": t.team_id,
                "name": t.name,
                "participant_id": t.participant_id,
                "participant_name": by_pid[t.participant_id].name if t.participant_id in by_pid else None,
                "autopick": t.autopick,
                "is_cpu": t.participant_id is None,
                "online": t.participant_id in online,
            }
            for t in st.teams
        ],
        "participants": [
            {
                "participant_id": p.participant_id,
                "name": p.name,
                "is_host": p.is_host,
                "online": p.participant_id in online,
                "team_id": (t.team_id if (t := st.team_for_participant(p.participant_id)) else None),
            }
            for p in st.participants
        ],
        "picks": [
            {
                "overall": p.overall,
                "round": p.round,
                "slot": p.slot,
                "original_team_id": p.original_team_id,
                "owner_team_id": p.owner_team_id,
                "player_id": p.player_id,
                "is_keeper": p.is_keeper,
                "auto": p.auto,
            }
            for p in picks
        ],
        "traded_picks": [
            {"round": int(k.split(":")[0]), "original_team_id": int(k.split(":")[1]), "owner_team_id": v}
            for k, v in sorted(st.pick_ownership.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(":")))
        ],
        "keepers": [asdict(k) for k in st.keepers],
        "current_overall": current.overall if current else None,
        "deadline": st.deadline,
        "paused_remaining": st.paused_remaining,
        "server_time": now,
        "chat": [asdict(c) for c in st.chat[-50:]],
        "problems": eng.validate_for_start(st) if st.status == "lobby" else [],
        "me": {
            "participant_id": viewer.participant_id if viewer else None,
            "name": viewer.name if viewer else None,
            "is_host": bool(viewer and viewer.is_host),
            "team_id": my_team.team_id if my_team else None,
            "queue": list(st.queues.get(viewer_id, [])) if viewer_id else [],
        },
    }
