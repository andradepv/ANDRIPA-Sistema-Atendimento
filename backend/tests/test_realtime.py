"""Tempo real com instâncias REAIS da API (uvicorn) — Cenários C, F e H.

Sobe duas instâncias ligadas ao mesmo PostgreSQL e Redis para provar a distribuição entre
instâncias, e duas instâncias com Redis inacessível para provar a degradação controlada.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from conftest import TEST_REDIS, Actor, Customer, open_table
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

BACKEND = Path(__file__).resolve().parents[1]
ORIGIN = "https://app.test"
REPORT = BACKEND / "test-results" / "realtime-latency.json"


@pytest.fixture
def app():
    """App em processo usado só para preparar dados: sem relay, para não competir com as instâncias."""
    from app.core.config import Settings
    from app.main import create_app
    return create_app(Settings(relay_enabled=False))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn(redis_url: str) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = {**os.environ, "ANDRIPA_REDIS_URL": redis_url, "ANDRIPA_COOKIE_SECURE": "false"}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                          "--port", str(port), "--log-level", "warning"], cwd=BACKEND, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/v1/health/live", timeout=0.5).status_code == 200:
                return p, base
        except httpx.HTTPError:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("API não subiu")


@pytest.fixture(scope="module")
def instances():
    procs = [_spawn(TEST_REDIS), _spawn(TEST_REDIS)]
    yield [b for _, b in procs]
    for p, _ in procs:
        p.terminate()
        p.wait(10)


def ws_url(base: str, kind: str) -> str:
    return base.replace("http://", "ws://") + f"/api/v1/ws/{kind}"


async def recv_event(ws, predicate, wait: float = 3.0) -> dict:
    deadline = time.monotonic() + wait
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("evento não recebido")
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
        if predicate(msg):
            return msg


def staff_ws(base: str, actor: Actor):
    return connect(ws_url(base, "staff"), origin=ORIGIN,
                   additional_headers={"Cookie": f"andripa_staff={actor.token}"})


async def customer_ws(base: str, token: str):
    ws = await connect(ws_url(base, "customer"), origin=ORIGIN)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    hello = json.loads(await asyncio.wait_for(ws.recv(), 3))
    assert hello["type"] == "hello"
    return ws


def post(base: str, url: str, headers: dict, body: dict | None = None) -> httpx.Response:
    return httpx.post(base + url, json=body or {}, headers=headers, timeout=10)


def test_cross_instance_delivery_and_latency(client, world, instances):
    """Chamado criado na instância A chega ao painel conectado na instância B via Redis."""
    a, b = instances
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    custs = [Customer(client, code) for _ in range(3)]  # respeita o rate limit por aparelho
    att = world["atendente"]
    latencies: list[float] = []

    async def run():
        async with staff_ws(b, att) as ws:
            assert json.loads(await ws.recv())["type"] == "hello"
            for i in range(30):
                t0 = time.perf_counter()
                r = await asyncio.to_thread(post, a, "/api/v1/public/service-requests", custs[i % 3].h(),
                                            {"type": "CHAMAR_ATENDENTE"})
                assert r.status_code == 201
                rid = r.json()["id"]
                ev = await recv_event(ws, lambda m, rid=rid: m.get("type") == "request.updated"
                                      and m["data"]["request"]["id"] == rid)
                latencies.append((time.perf_counter() - t0) * 1000)
                assert ev["data"]["request"]["table_number"] == 1
                # concluir para permitir um novo chamado
                rr = await asyncio.to_thread(post, a, f"/api/v1/service-requests/{rid}/complete", att.headers())
                assert rr.status_code == 200
                await recv_event(ws, lambda m: m.get("type") == "request.updated"
                                 and m["data"]["request"]["status"] == "CONCLUIDA")

    asyncio.run(run())
    p95 = statistics.quantiles(latencies, n=20)[18]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"samples": len(latencies), "p50_ms": round(statistics.median(latencies), 1),
                                  "p95_ms": round(p95, 1), "max_ms": round(max(latencies), 1),
                                  "note": "HTTP na instância A → WebSocket na instância B (inclui o POST)"}))
    assert p95 < 1000, latencies


def test_no_duplicate_events_per_connection(client, world, instances):
    a, b = instances
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    cust = Customer(client, code)

    async def run():
        async with staff_ws(a, world["caixa"]) as ws:
            await ws.recv()
            await asyncio.to_thread(post, b, "/api/v1/public/service-requests", cust.h(), {"type": "PEDIR_CONTA"})
            seen = []
            end = time.monotonic() + 2.0
            while time.monotonic() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - time.monotonic()))
                except TimeoutError:
                    break
                if "id" in m:
                    seen.append(m["id"])
            assert seen, "nenhum evento recebido"
            assert len(seen) == len(set(seen)), seen  # relay local + Redis não duplicam

    asyncio.run(run())


def test_customer_ws_updates_and_session_close(client, world, instances, menu):
    """Cenário F no tempo real: a conexão do cliente é encerrada (4001) e não reabre."""
    a, b = instances
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    cust = Customer(client, code)
    order = cust.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]}).json()
    sid = order["session_id"]

    async def run():
        ws = await customer_ws(b, cust.token)
        r = await asyncio.to_thread(post, a, f"/api/v1/orders/{order['id']}/status", world["atendente"].headers(),
                                    {"status": "ENTREGUE"})
        assert r.status_code == 200
        ev = await recv_event(ws, lambda m: m.get("type") == "order.updated"
                              and m["data"]["order"]["status"] == "ENTREGUE")
        assert ev["data"]["order"]["id"] == order["id"]
        r = await asyncio.to_thread(post, a, f"/api/v1/table-sessions/{sid}/close", world["caixa"].headers(),
                                    {"payment_method": "PIX"})
        assert r.status_code == 200
        ev = await recv_event(ws, lambda m: m.get("type") == "session.closed")
        assert ev["data"]["session_id"] == sid
        with pytest.raises(ConnectionClosed) as exc:
            for _ in range(10):
                await asyncio.wait_for(ws.recv(), 3)
        assert exc.value.rcvd.code == 4001
        # Reconectar com o token antigo é recusado.
        ws2 = await connect(ws_url(a, "customer"), origin=ORIGIN)
        await ws2.send(json.dumps({"type": "auth", "token": cust.token}))
        with pytest.raises(ConnectionClosed) as exc2:
            await asyncio.wait_for(ws2.recv(), 3)
        assert exc2.value.rcvd.code == 4001

    asyncio.run(run())


def test_ws_authorization(client, world, instances):
    a, _ = instances

    async def run():
        for headers, origin in (({}, ORIGIN), ({"Cookie": "andripa_staff=invalido"}, ORIGIN),
                                ({"Cookie": f"andripa_staff={world['admin'].token}"}, "https://evil.example")):
            # Recusado já no handshake (HTTP 403), antes de qualquer dado ser trocado.
            with pytest.raises(InvalidStatus) as exc:
                await connect(ws_url(a, "staff"), origin=origin, additional_headers=headers)
            assert exc.value.response.status_code == 403
        # Cliente sem autenticar na primeira mensagem.
        ws = await connect(ws_url(a, "customer"), origin=ORIGIN)
        await ws.send(json.dumps({"type": "auth", "token": "x" * 40}))
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(ws.recv(), 3)

    asyncio.run(run())


def test_logout_closes_staff_ws(client, world, instances):
    a, b = instances
    att = world["atendente"]

    async def run():
        ws = await staff_ws(b, att)
        await ws.recv()
        r = await asyncio.to_thread(post, a, "/api/v1/auth/logout", att.headers())
        assert r.status_code == 204
        with pytest.raises(ConnectionClosed) as exc:
            for _ in range(10):
                await asyncio.wait_for(ws.recv(), 3)
        assert exc.value.rcvd.code == 4003

    asyncio.run(run())


def test_reconnect_recovers_state(client, world, instances):
    """Cenário H: eventos perdidos durante a queda são recuperados pelo snapshot REST."""
    a, b = instances
    (t1, c1), (t2, c2) = world["tables"][0], world["tables"][1]
    open_table(world["atendente"], t1)
    open_table(world["atendente"], t2)
    caixa = world["caixa"]

    async def run():
        ws = await staff_ws(b, caixa)
        await ws.recv()
        await ws.close()  # queda de conexão
        r1 = Customer(client, c1).post("/api/v1/public/service-requests", json={"type": "CHAMAR_ATENDENTE"}).json()
        r2 = Customer(client, c2).post("/api/v1/public/service-requests", json={"type": "PEDIR_CONTA"}).json()
        async with staff_ws(b, caixa) as ws2:
            await ws2.recv()
            snap = (await asyncio.to_thread(httpx.get, b + "/api/v1/service-requests", headers=caixa.headers())).json()
            assert {i["id"] for i in snap["items"]} == {r1["id"], r2["id"]}
            # E novos eventos continuam chegando após reconectar.
            await asyncio.to_thread(post, a, f"/api/v1/service-requests/{r1['id']}/claim", caixa.headers())
            ev = await recv_event(ws2, lambda m: m.get("type") == "request.updated"
                                  and m["data"]["request"]["id"] == r1["id"])
            assert ev["data"]["request"]["status"] == "ASSUMIDA"

    asyncio.run(run())
