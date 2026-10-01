from backend.app import jobs as jobs_module
from backend.app.routers import sync as sync_router


def test_start_sync_runs_job_to_completion(client, monkeypatch):
    calls = []
    monkeypatch.setattr(sync_router, "sync_all", lambda league_id, **kwargs: calls.append((league_id, kwargs)))

    resp = client.post("/api/sync", json={"force_players": True})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert calls == [(None, {"force_players": True})]

    status_resp = client.get(f"/api/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "done"


def test_start_sync_passes_league_id_override_through(client, monkeypatch):
    calls = []
    monkeypatch.setattr(sync_router, "sync_all", lambda league_id, **kwargs: calls.append((league_id, kwargs)))

    resp = client.post("/api/sync", json={"league_id": "999999"})
    assert resp.status_code == 202
    assert calls == [("999999", {"force_players": False})]


def test_start_sync_rejects_when_already_running(client):
    job = jobs_module.create_job("sync")
    resp = client.post("/api/sync", json={})
    assert resp.status_code == 409
    job.status = "done"  # don't leak a stuck "pending" job into later tests


def test_start_sync_marks_job_failed_on_error(client, monkeypatch):
    def _boom(_league_id, **_kwargs):
        raise RuntimeError("sleeper is down")

    monkeypatch.setattr(sync_router, "sync_all", _boom)

    resp = client.post("/api/sync", json={})
    job_id = resp.json()["job_id"]

    status_resp = client.get(f"/api/jobs/{job_id}")
    assert status_resp.json()["status"] == "failed"
    assert "sleeper is down" in status_resp.json()["error"]


def test_start_rankings_sync_runs_job_to_completion(client, monkeypatch):
    calls = []
    monkeypatch.setattr(sync_router, "sync_rankings_all", lambda page, force: calls.append((page, force)))

    resp = client.post("/api/rankings/sync", json={"force": True, "page": "dynasty-superflex-overall"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert calls == [("dynasty-superflex-overall", True)]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"


def test_get_job_unknown_returns_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
