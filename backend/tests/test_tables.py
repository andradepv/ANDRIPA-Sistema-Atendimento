from concurrent.futures import ThreadPoolExecutor

from conftest import Actor, Customer, open_table, pg


def test_open_table_flow(world):
    att: Actor = world["atendente"]
    tid = world["tables"][0][0]
    r = open_table(att, tid)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "OCUPADA"
    assert t["session"]["label"] == "Família Silva"
    assert t["session"]["opened_by_name"].startswith("Atendente")
    assert len(t["session"]["join_code"]) == 4
    assert t["public_url"].startswith("https://app.test/m/")


def test_cannot_open_occupied(world):
    tid = world["tables"][0][0]
    assert open_table(world["atendente"], tid).status_code == 201
    r = open_table(world["caixa"], tid, pin="2222")
    assert r.status_code == 409 and r.json()["error"]["code"] == "table_not_free"


def test_open_requires_individual_confirmation(world):
    tid = world["tables"][0][0]
    r = open_table(world["atendente"], tid, pin="0000")
    assert r.status_code == 403 and r.json()["error"]["code"] == "confirmation_failed"
    # PIN de outro funcionário não serve.
    assert open_table(world["atendente"], tid, pin="2222").status_code == 403
    # A senha pessoal também é aceita como confirmação.
    assert open_table(world["atendente"], tid, pin="senha-de-teste-123").status_code == 201


def test_open_idempotent_replay(world):
    tid = world["tables"][0][0]
    r1 = open_table(world["atendente"], tid, key="abrir-mesa-1-xyz")
    r2 = open_table(world["atendente"], tid, key="abrir-mesa-1-xyz")
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["session"]["id"] == r2.json()["session"]["id"]
    assert r2.headers.get("idempotent-replay") == "true"


def test_concurrent_open_creates_single_session(world):
    """Cenário G: vários funcionários abrindo a mesma mesa simultaneamente."""
    tid = world["tables"][1][0]
    actors = [(world["atendente"], "3333"), (world["caixa"], "2222"), (world["admin"], "1111")] * 3
    with ThreadPoolExecutor(max_workers=9) as ex:
        results = list(ex.map(lambda ap: open_table(ap[0], tid, pin=ap[1]), actors))
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
    open_table(a, t["id"], pin="1111")
    assert a.patch(f"/api/v1/tables/{t['id']}", json={"number": 11}).status_code == 409


def test_close_flow_and_token_revocation(world, client):
    """Cenários E e F."""
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    cust = Customer(client, code)
    r = cust.post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"})
    assert r.status_code == 201
    table = world["caixa"].get("/api/v1/tables").json()[0]
    assert table["status"] == "ENCERRAMENTO_SOLICITADO"  # continua ocupada até o encerramento
    sid = table["session"]["id"]
    r = world["caixa"].post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "PIX"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CLOSED"
    assert world["caixa"].get("/api/v1/tables").json()[0]["status"] == "LIVRE"
    # Página antiga aberta: qualquer ação falha.
    assert cust.get("/api/v1/public/session").status_code == 401
    assert cust.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).status_code == 401
    assert cust.post("/api/v1/public/orders", json={"items": []}).status_code in (401, 422)
    # Fechar de novo não duplica.
    assert world["caixa"].post(f"/api/v1/table-sessions/{sid}/close",
                               json={"payment_method": "PIX"}).status_code == 409
    # Histórico.
    hist = world["caixa"].get("/api/v1/table-sessions").json()
    assert hist["total"] == 1 and hist["items"][0]["payment_method"] == "PIX"


def test_old_token_cannot_reach_new_session(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    old = Customer(client, code)
    sid = world["caixa"].get("/api/v1/tables").json()[0]["session"]["id"]
    world["caixa"].post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "DINHEIRO"})
    open_table(world["atendente"], tid, label="Outra família")
    new = Customer(client, code)
    assert old.get("/api/v1/public/session").status_code == 401
    assert old.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).status_code == 401
    assert new.get("/api/v1/public/session").status_code == 200
    reqs = world["caixa"].get("/api/v1/service-requests").json()
    assert reqs["total"] == 0


def test_cancel_close_request(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    Customer(client, code).post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"})
    r = world["caixa"].post(f"/api/v1/tables/{tid}/cancel-close-request")
    assert r.status_code == 200 and r.json()["status"] == "OCUPADA"
    assert world["caixa"].get("/api/v1/service-requests").json()["total"] == 0


def test_staff_request_close_and_free_table_transitions(world):
    tid = world["tables"][0][0]
    r = world["atendente"].post(f"/api/v1/tables/{tid}/request-close")
    assert r.status_code == 409  # mesa livre
    open_table(world["atendente"], tid)
    r = world["atendente"].post(f"/api/v1/tables/{tid}/request-close")
    assert r.status_code == 200 and r.json()["status"] == "ENCERRAMENTO_SOLICITADO"
