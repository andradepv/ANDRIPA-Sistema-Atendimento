from concurrent.futures import ThreadPoolExecutor

from conftest import Actor, Customer, make_user, open_table


def _call(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    return c, c.post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()["id"]


def test_concurrent_complete_only_once(client, world):
    """Várias pessoas tocando em “Atendido” ao mesmo tempo: só uma registra."""
    _, rid = _call(world, client)
    others = [Actor(client, *make_user(world["est"], "ATENDENTE")) for _ in range(5)]
    with ThreadPoolExecutor(max_workers=5) as ex:
        rs = list(ex.map(lambda a: a.post(f"/api/v1/service-requests/{rid}/complete"), others))
    codes = sorted(r.status_code for r in rs)
    assert codes.count(200) == 1 and codes.count(409) == 4, codes
    assert next(r for r in rs if r.status_code == 409).json()["error"]["code"] == "already_done"


def test_anyone_on_staff_marks_call_as_done(client, world):
    """Sem “quem assumiu”: qualquer pessoa da equipe resolve e o horário fica registrado."""
    c, rid = _call(world, client)
    r = world["atendente"].post(f"/api/v1/service-requests/{rid}/complete")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "CONCLUIDA" and body["completed_by_name"].startswith("Atendente")
    assert world["caixa"].get("/api/v1/service-requests").json()["total"] == 0
    mine = c.get("/api/v1/public/session").json()["requests"][0]
    assert mine["status"] == "CONCLUIDA" and mine["completed_at"]


def test_pending_ordered_oldest_first(client, world):
    (t1, c1), (t2, c2) = world["tables"][0], world["tables"][1]
    open_table(world["atendente"], t1)
    open_table(world["atendente"], t2)
    a = Customer(client, c1).post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()
    b = Customer(client, c2).post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}).json()
    items = world["atendente"].get("/api/v1/service-requests").json()["items"]
    assert [i["id"] for i in items] == [a["id"], b["id"]]
    t = {x["number"]: x for x in world["atendente"].get("/api/v1/tables").json()}
    assert t[1]["pending_calls"] == 1 and t[2]["bill_requested"] is True


def test_pending_requests_survive_reload(client, world):
    """Notificações não somem ao recarregar: o painel sempre lê do banco."""
    _, rid = _call(world, client)
    for _ in range(3):
        items = world["caixa"].get("/api/v1/service-requests").json()["items"]
        assert [i["id"] for i in items] == [rid]
