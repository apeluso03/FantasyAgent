"""Mock draft simulator routes: lobby, invites, traded picks, keepers, the
CPU driver, and the websocket."""

from __future__ import annotations

import time

import pytest
from fantasy_agent.db.models import MockAdpRecord
from fantasy_agent.mock_draft.sleeper_import import ImportedTeam, LeagueImport
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.main import app
from backend.app.routers import mock as mock_router


@pytest.fixture()
def board(db):
    mix = ["QB", "RB", "WR", "WR", "RB", "QB", "WR", "TE", "RB", "WR"]
    adp = 1
    for _ in range(50):
        for pos in mix:
            db.add(
                MockAdpRecord(
                    player_id=f"p{adp}", name=f"{pos} Player {adp}", position=pos, team="DAL",
                    adp_2027=adp, adp_dynasty=adp, adp_redraft=adp, is_rookie=(adp % 25 == 0), sources=[],
                )
            )
            adp += 1
    for i in range(20):
        db.add(
            MockAdpRecord(
                player_id=f"k{i}", name=f"Kicker {i}", position="K", team="DAL",
                adp_2027=adp, adp_dynasty=adp, adp_redraft=adp, is_rookie=False, sources=[],
            )
        )
        adp += 1
    db.commit()


def _create(client, **settings):
    body = {"name": "Test Mock", "settings": {"cpu_pick_seconds": 0, **settings}}
    r = client.post("/api/mock/drafts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _act(client, draft, token, **action):
    return client.post(
        f"/api/mock/drafts/{draft['draft_id']}/actions", json=action, headers={"X-Mock-Token": token}
    )


def _state(client, draft, token):
    r = client.get(f"/api/mock/drafts/{draft['draft_id']}", headers={"X-Mock-Token": token})
    assert r.status_code == 200, r.text
    return r.json()


def _wait_for(client, draft, token, predicate, timeout=10.0):
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        st = _state(client, draft, token)
        if predicate(st):
            return st
        time.sleep(0.05)
    raise AssertionError(f"condition not met; last status={st and st['status']} current={st and st['current_overall']}")


def test_create_requires_account(anon_client, board):
    assert anon_client.post("/api/mock/drafts", json={}).status_code == 401


def test_create_defaults_and_pool(client, board):
    d = _create(client)
    st = _state(client, d, d["token"])
    assert st["settings"]["num_teams"] == 12 and st["settings"]["rounds"] == 16
    assert st["settings"]["roster_slots"]["SUPER_FLEX"] == 1
    assert st["me"]["is_host"] and st["me"]["team_id"] == st["teams"][0]["team_id"]
    assert len(st["picks"]) == 192
    pool = client.get(f"/api/mock/drafts/{d['draft_id']}/pool", headers={"X-Mock-Token": d["token"]}).json()
    assert pool[0]["adp"] == 1.0 and any(p["position"] == "K" for p in pool)


def test_invite_join_without_account(client, board):
    d = _create(client, num_teams=4, rounds=3)
    with TestClient(app) as guest:
        info = guest.get(f"/api/mock/invite/{d['invite_code']}").json()
        assert info["open_seats"] == 3
        j = guest.post(f"/api/mock/invite/{d['invite_code']}/join", json={"name": "Friend"})
        assert j.status_code == 200, j.text
        g = j.json()
        st = _state(guest, d, g["token"])
        assert st["me"]["team_id"] == st["teams"][1]["team_id"]
        assert st["teams"][1]["name"] == "Friend"
        # Guests can't use host actions...
        assert _act(guest, d, g["token"], type="start").status_code == 403
        # ...and can't see anything without a token.
        assert guest.get(f"/api/mock/drafts/{d['draft_id']}").status_code == 401


def test_traded_picks_and_keepers(client, board):
    d = _create(client, num_teams=4, rounds=3)
    tok = d["token"]
    # Team 4 gets Team 1's and Team 2's 2nd-round picks; Team 3's 3rd is removed.
    assert _act(client, d, tok, type="set_pick_owner", round=2, original_team_id=1, owner_team_id=4).status_code == 200
    assert _act(client, d, tok, type="set_pick_owner", round=2, original_team_id=2, owner_team_id=4).status_code == 200
    st = _act(client, d, tok, type="set_pick_owner", round=3, original_team_id=3, owner_team_id=None).json()
    r2 = [p for p in st["picks"] if p["round"] == 2]
    assert sum(p["owner_team_id"] == 4 for p in r2) == 3
    assert len(st["picks"]) == 11
    assert {"round": 2, "original_team_id": 1, "owner_team_id": 4} in st["traded_picks"]

    st = _act(client, d, tok, type="set_keepers", keepers=[{"team_id": 2, "player_id": "p3", "round": 1}]).json()
    kept = next(p for p in st["picks"] if p["player_id"] == "p3")
    assert kept["is_keeper"] and kept["owner_team_id"] == 2 and kept["round"] == 1

    # A keeper in a round the team has no pick in is flagged before start.
    st = _act(client, d, tok, type="set_keepers", keepers=[{"team_id": 2, "player_id": "p3", "round": 2}]).json()
    assert st["problems"]
    assert _act(client, d, tok, type="start").status_code == 409


def test_cpu_drafts_around_the_host(client, board):
    d = _create(client, num_teams=4, rounds=3, pick_seconds=0)
    tok = d["token"]
    st = _act(client, d, tok, type="start").json()
    host_team = st["me"]["team_id"]
    assert st["current_overall"] == 1
    assert _act(client, d, tok, type="pick", player_id="p1").status_code == 200
    # CPUs take picks 2-7 (snake), then it's the host again at 8.
    st = _wait_for(client, d, tok, lambda s: s["current_overall"] == 8)
    assert next(p for p in st["picks"] if p["overall"] == 8)["owner_team_id"] == host_team
    assert all(p["player_id"] and p["auto"] for p in st["picks"][1:7])
    # Already drafted.
    assert _act(client, d, tok, type="pick", player_id="p1").status_code == 409


def test_autopick_finishes_the_draft_and_exports(client, board):
    d = _create(client, num_teams=3, rounds=4, pick_seconds=0)
    tok = d["token"]
    _act(client, d, tok, type="autopick", enabled=True)
    _act(client, d, tok, type="start")
    st = _wait_for(client, d, tok, lambda s: s["status"] == "complete")
    assert all(p["player_id"] for p in st["picks"])
    csv = client.get(f"/api/mock/drafts/{d['draft_id']}/export.csv", headers={"X-Mock-Token": tok})
    assert csv.status_code == 200 and csv.text.count("\n") == 13
    # Undo reopens a finished draft.
    _act(client, d, tok, type="autopick", enabled=False)
    st = _act(client, d, tok, type="undo").json()
    assert st["status"] == "drafting"


def test_timeout_autopicks_from_queue_and_turns_on_autopick(client, board):
    d = _create(client, num_teams=2, rounds=2, pick_seconds=1)
    tok = d["token"]
    _act(client, d, tok, type="queue", player_ids=["p40", "p41"])
    _act(client, d, tok, type="start")
    # Pick 1 times out -> queue's first player, and autopick turns on, so
    # Team 1's next pick (4th overall, snake) is made from the queue at once.
    st = _wait_for(client, d, tok, lambda s: s["status"] == "complete", timeout=6)
    assert st["teams"][0]["autopick"] is True
    mine = [p["player_id"] for p in st["picks"] if p["owner_team_id"] == st["me"]["team_id"]]
    assert mine == ["p40", "p41"]
    assert st["me"]["queue"] == []
    assert any("ran out of time" in c["text"] for c in st["chat"])


def test_pause_blocks_picks(client, board):
    d = _create(client, num_teams=2, rounds=2, pick_seconds=0)
    tok = d["token"]
    _act(client, d, tok, type="start")
    assert _act(client, d, tok, type="pause").status_code == 200
    assert _act(client, d, tok, type="pick", player_id="p1").status_code == 409
    _act(client, d, tok, type="resume")
    assert _act(client, d, tok, type="pick", player_id="p1").status_code == 200


def test_websocket_pushes_state(client, board):
    d = _create(client, num_teams=2, rounds=1, pick_seconds=0)
    tok = d["token"]
    with client.websocket_connect(f"/api/mock/drafts/{d['draft_id']}/ws?token={tok}") as ws:
        first = ws.receive_json()
        assert first["type"] == "state" and first["state"]["status"] == "lobby"
        _act(client, d, tok, type="start")
        assert ws.receive_json()["state"]["status"] == "drafting"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] in {"pong", "state"}


def test_websocket_rejects_bad_token(client, board):
    d = _create(client, num_teams=2, rounds=1)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/mock/drafts/{d['draft_id']}/ws?token=nope") as ws:
            ws.receive_json()


def test_import_sleeper_league(client, board, monkeypatch):
    d = _create(client)
    fake = LeagueImport(
        league_id="L", league_name="Real League", season="2027", num_teams=10, rounds=18,
        roster_slots={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "SUPER_FLEX": 1, "K": 1, "DEF": 0, "BN": 8},
        teams=[ImportedTeam(team_id=i, name=f"Owner {i}") for i in range(1, 11)],
        traded_picks=[(2, 1, 2), (6, 1, 9)],
    )
    monkeypatch.setattr(mock_router, "import_league", lambda client, league_id, season: fake)
    st = _act(client, d, d["token"], type="import_sleeper", league_id="L").json()
    assert len(st["teams"]) == 10 and st["settings"]["rounds"] == 18
    assert st["teams"][0]["participant_id"] == st["me"]["participant_id"]
    assert {"round": 6, "original_team_id": 1, "owner_team_id": 9} in st["traded_picks"]
    owner_of = {(p["round"], p["original_team_id"]): p["owner_team_id"] for p in st["picks"]}
    assert owner_of[(2, 1)] == 2 and owner_of[(6, 1)] == 9


def test_host_can_reclaim_seat_from_account(client, board):
    d = _create(client, num_teams=2, rounds=1)
    r = client.post(f"/api/mock/drafts/{d['draft_id']}/host-token")
    assert r.status_code == 200
    new = r.json()["token"]
    assert _state(client, d, new)["me"]["is_host"]
    old = client.get(f"/api/mock/drafts/{d['draft_id']}", headers={"X-Mock-Token": d["token"]})
    assert old.status_code == 401
    assert [x["draft_id"] for x in client.get("/api/mock/drafts").json()] == [d["draft_id"]]


def test_settings_change_resizes_lobby(client, board):
    d = _create(client)
    body = {"num_teams": 8, "rounds": 14, "draft_type": "3rr", "pick_seconds": 90, "cpu_pick_seconds": 0}
    st = _act(client, d, d["token"], type="update_settings", settings=body).json()
    assert len(st["teams"]) == 8 and len(st["picks"]) == 112
    assert st["settings"]["draft_type"] == "3rr"


def test_first_draft_on_empty_database_builds_board(client, monkeypatch):
    """A fresh deploy has no ADP board: the first draft builds it in its own
    committed transaction (regression: building it inside the request's
    session locked SQLite when the room was saved)."""
    from fantasy_agent.mock_draft import store

    calls = []

    def fake_refresh(session, **_):
        calls.append(1)
        for i in range(1, 301):
            pos = ["QB", "RB", "WR", "TE"][i % 4]
            session.add(MockAdpRecord(
                player_id=f"x{i}", name=f"P{i}", position=pos, team="DAL",
                adp_2027=i, adp_dynasty=i, adp_redraft=i, is_rookie=False, sources=[],
            ))
        for i in range(12):
            session.add(MockAdpRecord(
                player_id=f"xk{i}", name=f"K{i}", position="K", team="DAL",
                adp_2027=400 + i, adp_dynasty=400 + i, adp_redraft=400 + i, is_rookie=False, sources=[],
            ))
        session.add(store.SyncMeta(resource=store.RESOURCE, last_synced_at=store.dt.datetime.now(store.dt.timezone.utc)))
        session.flush()

    monkeypatch.setattr(store, "refresh_board", fake_refresh)
    d = _create(client)
    assert calls == [1]
    pool = client.get(f"/api/mock/drafts/{d['draft_id']}/pool", headers={"X-Mock-Token": d["token"]}).json()
    assert pool[0]["player_id"] == "x1"
    # Second draft reuses the board.
    _create(client)
    assert calls == [1]
