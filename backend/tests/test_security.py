from conftest import Customer, open_table, pg


def test_body_size_limit(client, world):
    big = {"name": "x" * 70_000}
    r = world["admin"].post("/api/v1/menu/categories", json=big)
    assert r.status_code == 413


def test_invalid_uuid_and_json(client, world):
    assert world["admin"].patch("/api/v1/tables/not-a-uuid", json={"name": "x"}).status_code == 422
    r = client.post("/api/v1/auth/login", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_sql_injection_strings_are_data(client, world):
    payload = "'; DROP TABLE tables; --"
    a = world["admin"]
    r = a.post("/api/v1/menu/categories", json={"name": payload})
    assert r.status_code == 201 and r.json()["name"] == payload
    with pg() as c:
        assert c.execute("SELECT count(*) FROM tables").fetchone()[0] == 3


def test_security_headers(client, world):
    r = world["admin"].get("/api/v1/tables")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers


def test_cors_restricted(client):
    r = client.options("/api/v1/auth/login", headers={"origin": "https://evil.example",
                                                       "access-control-request-method": "POST"})
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
    ok = client.options("/api/v1/auth/login", headers={"origin": "https://app.test",
                                                        "access-control-request-method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://app.test"


def test_customer_token_forgery(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    Customer(client, code)
    for bad in ("", "Bearer", "Bearer abc", "Bearer " + "A" * 43, "Basic xyz"):
        r = client.get("/api/v1/public/session", headers={"authorization": bad})
        assert r.status_code == 401


def test_tokens_not_stored_in_plaintext(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    cust = Customer(client, code)
    with pg() as c:
        hashes = [r[0] for r in c.execute("SELECT token_hash FROM customer_tokens").fetchall()]
        staff = [r[0] for r in c.execute("SELECT token_hash FROM staff_sessions").fetchall()]
        pw = c.execute("SELECT password_hash FROM users LIMIT 1").fetchone()[0]
    assert cust.token not in hashes and len(hashes[0]) == 64
    assert world["admin"].token not in staff
    assert pw.startswith("$argon2id$")


def test_audit_trail(client, world):
    tid = world["tables"][0][0]
    open_table(world["atendente"], tid)
    logs = world["admin"].get("/api/v1/admin/audit-logs").json()
    actions = {item["action"] for item in logs["items"]}
    assert {"auth.login", "table.open"} <= actions
    assert all("password" not in str(i["details"]).lower() or "changed" in str(i["details"]) for i in logs["items"])


def test_health(client):
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    assert client.get("/api/v1/health/ready").json() == {"status": "ok", "database": True, "redis": True}
