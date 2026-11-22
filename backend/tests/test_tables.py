from concurrent.futures import ThreadPoolExecutor

from conftest import Actor, Customer, close_table, open_table, open_with_pin, pg


def test_open_table_from_panel(world):
    att: Actor = world["atendente"]
    tid = world["tables"][0][0]
    r = open_table(att, tid)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "OCUPADA"
    assert t["session"]["opened_by_name"].startswith("Atendente")
    assert t["public_url"].startswith("https://app.test/m/")
    assert t["pending_calls"] == t["pending_orders"] == 0 and t["bill_requested"] is False


def test_open_table_with_pin_from_table_page(world, client):
    """“Liberar mesa”: na página da mesa, o atendente digita só o PIN."""
    tid, code = world["tables"][0]
    assert client.get(f"/api/v1/public/tables/{code}").json()["available"] is False
    r = open_with_pin(client, code, "0000")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_pin"
    r = open_with_pin(client, code, "3333")
    assert r.status_code == 201, r.text
    assert r.json()["available"] is True and r.json()["table_number"] == 1
    t = world["caixa"].get("/api/v1/tables").json()[0]
    assert t["status"] == "OCUPADA" and t["session"]["opened_by_name"].startswith("Atendente")
    # Mesa já liberada: o PIN não abre de novo.
    r = open_with_pin(client, code, "2222")
    assert r.status_code == 409 and r.json()["error"]["code"] == "table_not_free"
    # Tentativa com PIN errado fica na auditoria.
    with pg() as c:
        n = c.execute("SELECT count(*) FROM audit_logs WHERE action='table.open_denied'").fetchone()[0]
    assert n == 1


def test_inactive_staff_pin_does_not_open(world, client):
    tid, code = world["tables"][0]
    with pg() as c:
        c.execute("UPDATE users SET active=false WHERE username='atendente'")
    assert open_with_pin(client, code, "3333").status_code == 403


def test_pin_brute_force_is_rate_limited(world, client):
    _, code = world["tables"][0]
    codes = [open_with_pin(client, code, f"{i:04d}").status_code for i in range(4000, 4015)]
    assert 429 in codes


def test_cannot_open_occupied(world):
    tid = world["tables"][0][0]
    assert open_table(world["atendente"], tid).status_code == 201
    r = open_table(world["caixa"], tid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "table_not_free"


def test_open_idempotent_replay(world):
    tid = world["tables"][0][0]
    r1 = open_table(world["atendente"], tid, key="abrir-mesa-1-xyz")
    r2 = open_table(world["atendente"], tid, key="abrir-mesa-1-xyz")
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["session"]["id"] == r2.json()["session"]["id"]
    assert r2.headers.get("idempotent-replay") == "true"


def test_concurrent_open_creates_single_session(world, client):
    """Cenário G: painel e página da mesa liberando a mesma mesa ao mesmo tempo."""
    tid, code = world["tables"][1]
    calls = [lambda a=a: open_table(world[a], tid) for a in ("atendente", "caixa", "admin")] * 2
    calls += [lambda p=p: open_with_pin(client, code, p) for p in ("1111", "2222", "3333")]
    with ThreadPoolExecutor(max_workers=9) as ex:
        results = list(ex.map(lambda f: f(), calls))
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1, codes
    assert codes.count(409) == 8
    with pg() as c:
        n = c.execute("SELECT count(*) FROM table_sessions WHERE table_id=%s AND status='OPEN'", (tid,)).fetchone()[0]
    assert n == 1


def test_admin_table_management_and_qr(world):
    a: Actor = world["admin"]
    r = a.post("/api/v1/tables", json={"number": 10, "name": "Varanda"})
    assert r.status_code == 201
    t = r.json()
    assert a.post("/api/v1/tables", json={"number": 10}).status_code == 409
    qr = a.get(f"/api/v1/tables/{t['id']}/qr.svg")
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml") and b"<svg" in qr.content and b"xmlns" in qr.content
    old = t["public_url"]
    rot = a.post(f"/api/v1/tables/{t['id']}/rotate-code").json()
    assert rot["public_url"] != old
    # Renumerar mesa ocupada é bloqueado.
    open_table(a, t["id"])
    assert a.patch(f"/api/v1/tables/{t['id']}", json={"number": 11}).status_code == 409


def test_bill_finished_closes_table_and_revokes_tokens(world, client):
    """Cenários E e F: pedir a conta → “conta finalizada” → mesa livre e celular sem acesso."""
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    cust = Customer(client, code)
    call = cust.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()
    bill = cust.post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}).json()
    table = world["caixa"].get("/api/v1/tables").json()[0]
    assert table["status"] == "OCUPADA" and table["bill_requested"] is True and table["pending_calls"] == 1
    r = world["caixa"].post(f"/api/v1/service-requests/{bill['id']}/complete")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CONCLUIDA" and r.json()["completed_at"]
    assert r.json()["completed_by_name"].startswith("Caixa")
    t = world["caixa"].get("/api/v1/tables").json()[0]
    assert t["status"] == "LIVRE" and t["session"] is None
    # Página antiga aberta: qualquer ação falha.
    assert cust.get("/api/v1/public/session").status_code == 401
    assert cust.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).status_code == 401
    assert cust.post("/api/v1/public/orders", json={"items": []}).status_code in (401, 422)
    # Finalizar de novo não duplica.
    assert world["caixa"].post(f"/api/v1/service-requests/{bill['id']}/complete").status_code == 409
    assert close_table(world["caixa"], tid).status_code == 409
    # Histórico da mesa com horários de cada solicitação; o chamado sem resposta ficou cancelado.
    hist = world["caixa"].get(f"/api/v1/table-sessions?table_id={tid}").json()
    assert hist["total"] == 1 and hist["items"][0]["requests_count"] == 2
    detail = world["caixa"].get(f"/api/v1/table-sessions/{hist['items'][0]['id']}").json()
    statuses = {x["id"]: x["status"] for x in detail["requests"]}
    assert statuses == {call["id"]: "CANCELADA", bill["id"]: "CONCLUIDA"}
    assert detail["closed_at"] and detail["closed_by_name"].startswith("Caixa")


def test_close_table_without_bill_request(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    Customer(client, code)
    r = close_table(world["caixa"], tid, key="fechar-mesa-1-abc")
    assert r.status_code == 200 and r.json()["status"] == "LIVRE"
    assert close_table(world["caixa"], tid, key="fechar-mesa-1-abc").headers.get("idempotent-replay") == "true"


def test_old_token_cannot_reach_new_session(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    old = Customer(client, code)
    close_table(world["caixa"], tid)
    open_with_pin(client, code, "3333")
    new = Customer(client, code)
    assert old.get("/api/v1/public/session").status_code == 401
    assert old.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).status_code == 401
    assert new.get("/api/v1/public/session").status_code == 200
    assert world["caixa"].get("/api/v1/service-requests").json()["total"] == 0
