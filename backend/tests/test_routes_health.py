def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_health_reports_app_mode(anon_client):
    # The frontend reads this at load to decide whether it's a mock-only site.
    assert anon_client.get("/api/health").json()["mode"] == "full"
