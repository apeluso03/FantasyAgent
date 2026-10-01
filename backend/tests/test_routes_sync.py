import datetime as dt

from fantasy_agent.db.models import SyncMeta


def test_sync_status_empty(client):
    resp = client.get("/api/sync/status")
    assert resp.status_code == 200
    assert resp.json() == []


def test_sync_status_lists_resources(client, db):
    db.add(SyncMeta(resource="players", last_synced_at=dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)))
    db.commit()

    resp = client.get("/api/sync/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"resource": "players", "last_synced_at": "2026-09-01T00:00:00+00:00"}]
