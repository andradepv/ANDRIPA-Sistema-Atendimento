from concurrent.futures import ThreadPoolExecutor

from conftest import Customer, make_est, make_table, open_table, pg


def test_public_table_free_is_unavailable(client, world):
    """Cenário B."""
    _, code = world["tables"][0]
    r = client.get(f"/api/v1/public/tables/{code}")
    assert r.status_code == 200
    assert r.json()["available"] is False and r.json()["table_number"] == 1
    j = client.post(f"/api/v1/public/tables/{code}/join", json={})
    assert j.status_code == 409 and j.json()["error"]["code"] == "table_not_open"


def test_unknown_or_guessed_codes(client, world):
    for code in ("1", "mesa-1", "A" * 22, "../../etc", "' OR 1=1 --"):
        r = client.get(f"/api/v1/public/tables/{code}")
        assert r.status_code == 404, code


def test_public_payload_has_no_internal_ids(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    body = client.get(f"/api/v1/public/tables/{code}").text
    assert tid not in body and "join_code\":\"" not in body


def test_call_attendant_flow_and_dedup(client, world):
    """Cenário C (parte HTTP) e proteção contra cliques repetidos."""
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    r1 = c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"})
    r2 = c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"})
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"] and r1.json()["status"] == "PENDENTE"
    staff = world["atendente"].get("/api/v1/service-requests").json()
    assert staff["total"] == 1 and staff["items"][0]["table_number"] == 1
    rid = r1.json()["id"]
    assert world["atendente"].post(f"/api/v1/service-requests/{rid}/claim").json()["status"] == "ASSUMIDA"
    assert world["atendente"].post(f"/api/v1/service-requests/{rid}/complete").json()["status"] == "CONCLUIDA"
    # Concluído o chamado, um novo chamado legítimo é permitido.
    r3 = c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"})
    assert r3.status_code == 201 and r3.json()["id"] != rid
    state = c.get("/api/v1/public/session").json()
    assert {r["status"] for r in state["requests"]} == {"PENDENTE", "CONCLUIDA"}


def test_concurrent_calls_single_active(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    customers = [Customer(client, code) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=12) as ex:
        rs = list(ex.map(lambda i: customers[i % 4].post("/api/v1/public/service-requests",
                                                         json={"type": "CHAMAR_ATENDENTE"}), range(12)))
    assert all(r.status_code == 201 for r in rs), [r.text for r in rs if r.status_code != 201]
    assert len({r.json()["id"] for r in rs}) == 1
    with pg() as cn:
        n = cn.execute("SELECT count(*) FROM service_requests WHERE type='CHAMAR_ATENDENTE'").fetchone()[0]
    assert n == 1


def test_idempotency_key_same_request(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    h = {"idempotency-key": "cliente-req-0001"}
    r1 = c.post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}, headers=h)
    r2 = c.post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}, headers=h)
    assert r1.json() == r2.json() and r2.headers.get("idempotent-replay") == "true"
    r3 = c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}, headers=h)
    assert r3.status_code == 422 and r3.json()["error"]["code"] == "idempotency_key_reused"


def test_customer_can_cancel_pending_call(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    rid = c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()["id"]
    assert c.post(f"/api/v1/public/service-requests/{rid}/cancel").json()["status"] == "CANCELADA"


def test_customer_cannot_touch_other_table(client, world):
    (t1, c1), (t2, c2) = world["tables"][0], world["tables"][1]
    open_table(world["atendente"], t1)
    open_table(world["atendente"], t2)
    a, b = Customer(client, c1), Customer(client, c2)
    rid = b.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()["id"]
    assert a.post(f"/api/v1/public/service-requests/{rid}/cancel").status_code == 404
    # Campos extras (ex.: session_id/table_id) são rejeitados — não há como "apontar" outra mesa.
    r = a.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE", "session_id": rid})
    assert r.status_code == 422
    assert a.get("/api/v1/public/session").json()["table_number"] == 1


def test_join_code_required(client):
    est = make_est("Bar Código", join_code_required=True)
    from conftest import Actor, make_user
    att = Actor(client, make_user(est, "ATENDENTE", pin="4444"))
    tid, code = make_table(est, 1)
    jc = open_table(att, tid, pin="4444").json()["session"]["join_code"]
    assert client.get(f"/api/v1/public/tables/{code}").json()["join_code_required"] is True
    assert client.post(f"/api/v1/public/tables/{code}/join", json={}).status_code == 403
    bad = "0000" if jc != "0000" else "1111"
    assert client.post(f"/api/v1/public/tables/{code}/join", json={"join_code": bad}).status_code == 403
    assert client.post(f"/api/v1/public/tables/{code}/join", json={"join_code": jc}).status_code == 200
    # Força bruta é limitada.
    codes = [client.post(f"/api/v1/public/tables/{code}/join", json={"join_code": bad}).status_code for _ in range(12)]
    assert 429 in codes


def test_customer_request_rate_limit(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    codes = [c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).status_code
             for _ in range(30)]
    assert 429 in codes
