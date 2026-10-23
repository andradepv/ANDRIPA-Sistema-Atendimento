"""Redis indisponível: as instâncias seguem funcionando e entregam eventos lendo o outbox.

Arquivo separado para que nenhuma instância com Redis saudável esteja rodando ao mesmo tempo.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import Customer, open_table
from test_realtime import _spawn, post, recv_event, staff_ws


@pytest.fixture
def app():
    from app.core.config import Settings
    from app.main import create_app
    return create_app(Settings(relay_enabled=False))


@pytest.fixture(scope="module")
def degraded_instances():
    dead = "redis://127.0.0.1:6390/0"  # nenhuma instância Redis nesta porta
    procs = [_spawn(dead), _spawn(dead)]
    yield [b for _, b in procs]
    for p, _ in procs:
        p.terminate()
        p.wait(10)



def test_redis_unavailable_degrades_gracefully(client, world, degraded_instances):
    """Sem Redis: operações seguem persistidas e eventos chegam via outbox em ambas as instâncias."""
    a, b = degraded_instances
    ready = httpx.get(a + "/api/v1/health/ready").json()
    assert ready == {"status": "degraded", "database": True, "redis": False}
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    cust = Customer(client, code)

    async def run():
        async with staff_ws(b, world["atendente"]) as ws_b, staff_ws(a, world["caixa"]) as ws_a:
            await ws_b.recv()
            await ws_a.recv()
            r = await asyncio.to_thread(post, a, "/api/v1/public/service-requests", cust.h(),
                                        {"type": "CHAMAR_ATENDENTE"})
            assert r.status_code == 201
            rid = r.json()["id"]
            pred = lambda m: m.get("type") == "request.updated" and m["data"]["request"]["id"] == rid  # noqa: E731
            await recv_event(ws_a, pred, wait=5)   # mesma instância
            await recv_event(ws_b, pred, wait=5)   # outra instância, via leitura do outbox

    asyncio.run(run())
    # Rate limiting continua funcionando (limitador local).
    codes = [httpx.post(a + "/api/v1/auth/login", json={"email": "x@y.com", "password": "z"}).status_code
             for _ in range(12)]
    assert 429 in codes
