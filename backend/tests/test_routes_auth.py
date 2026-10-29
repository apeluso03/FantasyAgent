def test_signup_creates_account_and_returns_a_working_token(anon_client):
    resp = anon_client.post(
        "/api/auth/signup", json={"email": "new@example.com", "password": "correcthorse", "display_name": "Alex"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["account"]["email"] == "new@example.com"
    assert body["account"]["display_name"] == "Alex"
    assert "token" in body

    me = anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


def test_signup_rejects_duplicate_email(anon_client):
    anon_client.post("/api/auth/signup", json={"email": "dup@example.com", "password": "correcthorse"})
    resp = anon_client.post("/api/auth/signup", json={"email": "dup@example.com", "password": "anotherpass"})
    assert resp.status_code == 409


def test_signup_rejects_short_password(anon_client):
    resp = anon_client.post("/api/auth/signup", json={"email": "short@example.com", "password": "short"})
    assert resp.status_code == 422


def test_signup_rejects_invalid_email(anon_client):
    resp = anon_client.post("/api/auth/signup", json={"email": "not-an-email", "password": "correcthorse"})
    assert resp.status_code == 422


def test_login_succeeds_with_correct_credentials(anon_client):
    anon_client.post("/api/auth/signup", json={"email": "login@example.com", "password": "correcthorse"})
    resp = anon_client.post("/api/auth/login", json={"email": "login@example.com", "password": "correcthorse"})
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_login_rejects_wrong_password(anon_client):
    anon_client.post("/api/auth/signup", json={"email": "login2@example.com", "password": "correcthorse"})
    resp = anon_client.post("/api/auth/login", json={"email": "login2@example.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_rejects_unknown_email(anon_client):
    resp = anon_client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert resp.status_code == 401


def test_me_requires_a_token(anon_client):
    resp = anon_client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_rejects_an_unknown_token(anon_client):
    resp = anon_client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_update_me_persists_league_defaults(anon_client):
    signup = anon_client.post("/api/auth/signup", json={"email": "prefs@example.com", "password": "correcthorse"})
    headers = {"Authorization": f"Bearer {signup.json()['token']}"}

    resp = anon_client.patch(
        "/api/auth/me",
        json={"default_league_id": "999999", "default_owner_user_id": "111111"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["default_league_id"] == "999999"
    assert resp.json()["default_owner_user_id"] == "111111"

    me = anon_client.get("/api/auth/me", headers=headers)
    assert me.json()["default_league_id"] == "999999"


def test_logout_revokes_the_token(anon_client):
    signup = anon_client.post("/api/auth/signup", json={"email": "logout@example.com", "password": "correcthorse"})
    headers = {"Authorization": f"Bearer {signup.json()['token']}"}

    logout = anon_client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204

    me = anon_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 401


def test_gated_routes_require_authentication(anon_client):
    resp = anon_client.get("/api/league")
    assert resp.status_code == 401


def test_health_stays_public(anon_client):
    resp = anon_client.get("/api/health")
    assert resp.status_code == 200
