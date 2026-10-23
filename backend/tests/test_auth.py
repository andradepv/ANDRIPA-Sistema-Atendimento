from conftest import PASSWORD, Actor, make_est, make_user


def test_login_me_logout(client, world):
    a: Actor = world["atendente"]
    me = a.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["role"] == "ATENDENTE"
    assert "tables.open" in body["permissions"] and "users.manage" not in body["permissions"]
    assert a.post("/api/v1/auth/logout").status_code == 204
    # Token revogado não autentica mais.
    assert a.get("/api/v1/auth/me").status_code == 401


def test_login_cookie_flags(client, world):
    r = client.post("/api/v1/auth/login", json={"email": "caixa@teste.local", "password": PASSWORD})
    sc = [v for k, v in r.headers.multi_items() if k == "set-cookie"]
    staff = next(c for c in sc if c.startswith("andripa_staff="))
    assert "HttpOnly" in staff and "Secure" in staff and "SameSite=strict" in staff.replace("Strict", "strict")
    assert "andripa_staff" not in r.text  # token não vai no corpo


def test_wrong_password_and_unknown_user(client, world):
    assert client.post("/api/v1/auth/login", json={"email": "caixa@teste.local", "password": "errada"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "ninguem@teste.local", "password": "x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_inactive_user_cannot_login(client):
    est = make_est()
    email = make_user(est, "ATENDENTE")
    from conftest import pg
    with pg() as c:
        c.execute("UPDATE users SET active=false WHERE email=%s", (email,))
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_csrf_required_on_writes(client, world):
    a: Actor = world["admin"]
    r = client.post("/api/v1/tables", json={"number": 50}, headers={"cookie": f"andripa_staff={a.token}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = client.post("/api/v1/tables", json={"number": 50},
                    headers={"cookie": f"andripa_staff={a.token}", "x-csrf-token": "forjado"})
    assert r.status_code == 403
    assert a.post("/api/v1/tables", json={"number": 50}).status_code == 201


def test_login_rate_limited(client, world):
    codes = [client.post("/api/v1/auth/login", json={"email": "caixa@teste.local", "password": "errada"}).status_code
             for _ in range(10)]
    assert 429 in codes


def test_role_change_revokes_sessions(client, world):
    att: Actor = world["atendente"]
    users = world["admin"].get("/api/v1/admin/users").json()
    uid = next(u["id"] for u in users if u["email"] == "atendente@teste.local")
    assert world["admin"].patch(f"/api/v1/admin/users/{uid}", json={"role": "CAIXA"}).status_code == 200
    assert att.get("/api/v1/auth/me").status_code == 401  # precisa logar de novo para obter o novo papel


def test_cannot_remove_last_admin(client, world):
    me = world["admin"].me["user"]["id"]
    r = world["admin"].patch(f"/api/v1/admin/users/{me}", json={"active": False})
    assert r.status_code == 422


def test_change_own_pin_requires_password(client, world):
    att: Actor = world["atendente"]
    assert att.post("/api/v1/auth/credentials", json={"current_password": "x", "new_pin": "9999"}).status_code == 403
    assert att.post("/api/v1/auth/credentials", json={"current_password": PASSWORD, "new_pin": "9999"}).status_code == 204
