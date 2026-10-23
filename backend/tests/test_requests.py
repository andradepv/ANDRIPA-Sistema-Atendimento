from concurrent.futures import ThreadPoolExecutor

from conftest import Actor, Customer, make_user, open_table


def _call(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    return c, c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()["id"]


def test_concurrent_claim_single_owner(client, world):
    _, rid = _call(world, client)
    others = [Actor(client, make_user(world["est"], "ATENDENTE")) for _ in range(5)]
    with ThreadPoolExecutor(max_workers=5) as ex:
        rs = list(ex.map(lambda a: a.post(f"/api/v1/service-requests/{rid}/claim"), others))
    codes = sorted(r.status_code for r in rs)
    assert codes.count(200) == 1 and codes.count(409) == 4, codes
    loser = next(r for r in rs if r.status_code == 409).json()
    assert loser["error"]["code"] == "already_claimed" and loser["error"]["details"]["assigned_to"]


def test_only_assignee_or_supervisor_completes(client, world):
    _, rid = _call(world, client)
    other = Actor(client, make_user(world["est"], "ATENDENTE"))
    world["atendente"].post(f"/api/v1/service-requests/{rid}/claim")
    assert other.post(f"/api/v1/service-requests/{rid}/complete").status_code == 403
    assert world["caixa"].post(f"/api/v1/service-requests/{rid}/start").status_code == 200
    assert world["caixa"].post(f"/api/v1/service-requests/{rid}/complete").json()["status"] == "CONCLUIDA"
    assert world["caixa"].post(f"/api/v1/service-requests/{rid}/start").status_code == 409


def test_priority_and_ordering(client, world):
    (t1, c1), (t2, c2) = world["tables"][0], world["tables"][1]
    open_table(world["atendente"], t1)
    open_table(world["atendente"], t2)
    a = Customer(client, c1).post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()
    b = Customer(client, c2).post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()
    items = world["caixa"].get("/api/v1/service-requests").json()["items"]
    assert [i["id"] for i in items] == [a["id"], b["id"]]  # mais antigo primeiro
    assert world["atendente"].post(f"/api/v1/service-requests/{b['id']}/priority", json={"priority": 3}).status_code == 403
    assert world["caixa"].post(f"/api/v1/service-requests/{b['id']}/priority", json={"priority": 3}).status_code == 200
    items = world["caixa"].get("/api/v1/service-requests").json()["items"]
    assert items[0]["id"] == b["id"]


def test_attendant_cannot_complete_bill(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    rid = Customer(client, code).post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}).json()["id"]
    assert world["atendente"].post(f"/api/v1/service-requests/{rid}/claim").status_code == 200
    assert world["atendente"].post(f"/api/v1/service-requests/{rid}/complete").status_code == 403


def test_pending_requests_survive_reload(client, world):
    """Notificações não somem ao recarregar: o painel sempre lê do banco."""
    _, rid = _call(world, client)
    for _ in range(3):
        items = world["caixa"].get("/api/v1/service-requests").json()["items"]
        assert [i["id"] for i in items] == [rid]
