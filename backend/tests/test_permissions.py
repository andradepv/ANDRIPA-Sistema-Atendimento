"""Matriz de permissões aplicada no backend (Cenário I) e isolamento entre estabelecimentos."""
import uuid

import pytest
from conftest import Actor, make_est, make_table, make_user, open_table

ADMIN_ONLY = [
    ("post", "/api/v1/tables", {"number": 99}),
    ("get", "/api/v1/admin/users", None),
    ("post", "/api/v1/admin/users", {"name": "X", "email": "x@x.com", "role": "ADMIN", "password": "0123456789"}),
    ("get", "/api/v1/admin/audit-logs", None),
    ("patch", "/api/v1/admin/establishment", {"name": "Hack"}),
    ("post", "/api/v1/menu/categories", {"name": "Hack"}),
    ("get", "/api/v1/admin/promotions", None),
    ("post", "/api/v1/admin/push/broadcast", {"title": "a", "body": "b"}),
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


def test_attendant_cannot_close_or_view_cash(world):
    tid = world["tables"][0][0]
    assert open_table(world["atendente"], tid).status_code == 201
    sid = world["atendente"].get("/api/v1/tables").json()[0]["session"]["id"]
    r = world["atendente"].post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "PIX"})
    assert r.status_code == 403
    assert world["atendente"].get("/api/v1/table-sessions").status_code == 403
    assert world["caixa"].get("/api/v1/table-sessions").status_code == 200


def test_unauthenticated_denied(client, world):
    for url in ("/api/v1/tables", "/api/v1/service-requests", "/api/v1/orders", "/api/v1/admin/users"):
        assert client.get(url).status_code == 401


def test_admin_has_all_operational_powers(world):
    a: Actor = world["admin"]
    tid = world["tables"][0][0]
    assert open_table(a, tid, pin="1111").status_code == 201
    sid = a.get("/api/v1/tables").json()[0]["session"]["id"]
    assert a.post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "DINHEIRO"}).status_code == 200


def test_cross_establishment_isolation(client, world):
    other = make_est("Outro Bar")
    other_admin = Actor(client, make_user(other, "ADMIN"))
    other_tid, _ = make_table(other, 1)
    # O admin do outro bar não enxerga nem manipula mesas deste bar.
    tid = world["tables"][0][0]
    assert all(t["id"] != tid for t in other_admin.get("/api/v1/tables").json())
    assert other_admin.post(f"/api/v1/tables/{tid}/open", json={"confirm_secret": "senha-de-teste-123"}).status_code == 404
    assert other_admin.patch(f"/api/v1/tables/{tid}", json={"name": "x"}).status_code == 404
    # E vice-versa.
    assert world["admin"].patch(f"/api/v1/tables/{other_tid}", json={"name": "x"}).status_code == 404
    # Sessão de outro estabelecimento não é acessível.
    open_table(world["atendente"], tid)
    sid = world["atendente"].get("/api/v1/tables").json()[0]["session"]["id"]
    assert other_admin.get(f"/api/v1/table-sessions/{sid}").status_code == 404
    assert other_admin.post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "PIX"}).status_code == 404
    assert other_admin.get(f"/api/v1/service-requests/{uuid.uuid4()}/claim").status_code in (404, 405)
