"""Matriz de permissões aplicada no backend (Cenário I) e isolamento entre estabelecimentos."""
import pytest
from conftest import Actor, Customer, close_table, make_est, make_table, make_user, open_table

ADMIN_ONLY = [
    ("post", "/api/v1/tables", {"number": 99}),
    ("get", "/api/v1/admin/users", None),
    ("post", "/api/v1/admin/users", {"name": "X", "username": "xx", "role": "ADMIN", "pin": "8888"}),
    ("get", "/api/v1/admin/audit-logs", None),
    ("patch", "/api/v1/admin/establishment", {"name": "Hack"}),
    ("post", "/api/v1/menu/categories", {"name": "Hack"}),
    ("get", "/api/v1/admin/notices", None),
    ("post", "/api/v1/admin/notices", {"title": "a"}),
]


@pytest.mark.parametrize("method,url,body", ADMIN_ONLY)
@pytest.mark.parametrize("role", ["atendente", "caixa"])
def test_admin_functions_denied(world, role, method, url, body):
    actor: Actor = world[role]
    r = getattr(actor, method)(url, json=body) if body is not None else getattr(actor, method)(url)
    assert r.status_code == 403, (role, url, r.text)
    assert r.json()["error"]["code"] == "forbidden"


def test_privilege_escalation_body_ignored(world):
    """Atendente não consegue se promover nem enviando 'role' no corpo."""
    att: Actor = world["atendente"]
    uid = att.me["user"]["id"]
    assert att.patch(f"/api/v1/admin/users/{uid}", json={"role": "ADMIN"}).status_code == 403
    assert att.get("/api/v1/auth/me").json()["user"]["role"] == "ATENDENTE"


def test_attendant_cannot_finish_bill_or_view_history(world, client):
    tid, code = world["tables"][0]
    assert open_table(world["atendente"], tid).status_code == 201
    bill = Customer(client, code).post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}).json()
    assert close_table(world["atendente"], tid).status_code == 403
    r = world["atendente"].post(f"/api/v1/service-requests/{bill['id']}/complete")
    assert r.status_code == 403
    assert world["atendente"].get("/api/v1/table-sessions").status_code == 403
    assert world["caixa"].get("/api/v1/table-sessions").status_code == 200


def test_unauthenticated_denied(client, world):
    for url in ("/api/v1/tables", "/api/v1/service-requests", "/api/v1/admin/users", "/api/v1/table-sessions"):
        assert client.get(url).status_code == 401


def test_admin_has_all_operational_powers(world):
    a: Actor = world["admin"]
    tid = world["tables"][0][0]
    assert open_table(a, tid).status_code == 201
    assert close_table(a, tid).status_code == 200


def test_cross_establishment_isolation(client, world):
    other = make_est("Outro Bar")
    other_admin = Actor(client, *make_user(other, "ADMIN"))
    other_tid, other_code = make_table(other, 1)
    # O admin do outro bar não enxerga nem manipula mesas deste bar.
    tid, code = world["tables"][0]
    assert all(t["id"] != tid for t in other_admin.get("/api/v1/tables").json())
    assert open_table(other_admin, tid).status_code == 404
    assert other_admin.patch(f"/api/v1/tables/{tid}", json={"name": "x"}).status_code == 404
    # E vice-versa.
    assert world["admin"].patch(f"/api/v1/tables/{other_tid}", json={"name": "x"}).status_code == 404
    # O PIN da equipe de um bar não libera mesa de outro bar.
    assert client.post(f"/api/v1/public/tables/{other_code}/open", json={"pin": "3333"}).status_code == 403
    # Atendimento e solicitações de outro estabelecimento não são acessíveis.
    open_table(world["atendente"], tid)
    sid = world["atendente"].get("/api/v1/tables").json()[0]["session"]["id"]
    req = Customer(client, code).post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()
    assert other_admin.get(f"/api/v1/table-sessions/{sid}").status_code == 404
    assert close_table(other_admin, tid).status_code == 404
    assert other_admin.post(f"/api/v1/service-requests/{req['id']}/complete").status_code == 404
    assert other_admin.get("/api/v1/service-requests").json()["total"] == 0
