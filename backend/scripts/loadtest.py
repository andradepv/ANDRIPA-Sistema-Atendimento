"""Teste de carga controlado das leituras mais comuns.

Uso (com a API rodando e o seed de desenvolvimento aplicado):
    python scripts/loadtest.py --base http://localhost:8000 --email caixa@demo.local --password ... \
        --concurrency 20 --seconds 30

Mede latência por endpoint (p50/p95/p99) e taxa de erro; grava JSON em test-results/loadtest.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--pin", default="2222")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=30)
    a = ap.parse_args()

    async with httpx.AsyncClient(base_url=a.base, timeout=10) as c:
        r = await c.post("/api/v1/auth/login", json={"email": a.email, "password": a.password})
        r.raise_for_status()
        staff = {"cookie": f"andripa_staff={r.cookies['andripa_staff']}", "x-csrf-token": r.json()["csrf_token"]}
        tables = (await c.get("/api/v1/tables", headers=staff)).json()
        target = next((t for t in tables if t["status"] == "LIVRE"), None)
        if target is None:
            raise SystemExit("Nenhuma mesa livre para o teste.")
        r = await c.post(f"/api/v1/tables/{target['id']}/open", json={"label": "carga", "confirm_secret": a.pin},
                         headers=staff)
        r.raise_for_status()
        code = target["public_url"].rsplit("/", 1)[1]
        tok = (await c.post(f"/api/v1/public/tables/{code}/join", json={})).json()["token"]
        cust = {"authorization": f"Bearer {tok}"}

    endpoints = [
        ("GET /tables", "/api/v1/tables", staff),
        ("GET /service-requests", "/api/v1/service-requests?active=true", staff),
        ("GET /orders", "/api/v1/orders?active=true", staff),
        ("GET /public/menu", "/api/v1/public/menu", cust),
        ("GET /public/session", "/api/v1/public/session", cust),
    ]
    samples: dict[str, list[float]] = {name: [] for name, _, _ in endpoints}
    errors: dict[str, int] = {name: 0 for name, _, _ in endpoints}
    stop = time.monotonic() + a.seconds

    async def worker(i: int) -> None:
        async with httpx.AsyncClient(base_url=a.base, timeout=10) as c:
            n = i
            while time.monotonic() < stop:
                name, url, h = endpoints[n % len(endpoints)]
                n += 1
                t0 = time.perf_counter()
                try:
                    r = await c.get(url, headers=h)
                    ok = r.status_code == 200
                except httpx.HTTPError:
                    ok = False
                if ok:
                    samples[name].append((time.perf_counter() - t0) * 1000)
                else:
                    errors[name] += 1

    await asyncio.gather(*(worker(i) for i in range(a.concurrency)))

    def q(xs: list[float], p: int) -> float:
        return round(statistics.quantiles(xs, n=100)[p - 1], 1) if len(xs) >= 100 else round(max(xs), 1)

    report = {
        "concurrency": a.concurrency, "seconds": a.seconds,
        "endpoints": {n: {"requests": len(xs), "errors": errors[n], "p50_ms": round(statistics.median(xs), 1),
                          "p95_ms": q(xs, 95), "p99_ms": q(xs, 99)} for n, xs in samples.items() if xs},
    }
    total = sum(len(x) for x in samples.values())
    report["throughput_rps"] = round(total / a.seconds, 1)
    out = Path("test-results/loadtest.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
