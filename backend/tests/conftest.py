"""Testes de integração contra PostgreSQL e Redis REAIS (nada de SQLite).

Variáveis: ANDRIPA_TEST_DATABASE_URL e ANDRIPA_TEST_REDIS_URL (ver docker-compose.yml).
"""
from __future__ import annotations

import http.cookiejar
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

TEST_DB = os.environ.get("ANDRIPA_TEST_DATABASE_URL",
                         "postgresql+psycopg://atende:atende@127.0.0.1:5432/atende_test")
TEST_REDIS = os.environ.get("ANDRIPA_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")

os.environ.update({
    "ANDRIPA_ENVIRONMENT": "test",
    "ANDRIPA_DATABASE_URL": TEST_DB,
    "ANDRIPA_REDIS_URL": TEST_REDIS,
    "ANDRIPA_PUBLIC_BASE_URL": "https://app.test",
    "ANDRIPA_ALLOWED_ORIGINS": "https://testserver,https://app.test",
    "ANDRIPA_DB_NULL_POOL": "false",
    "ANDRIPA_DB_POOL_SIZE": "20",
    "ANDRIPA_OUTBOX_POLL_SECONDS": "0.1",
    "ANDRIPA_LOG_LEVEL": "WARNING",
    # Argon2id com custo reduzido apenas para acelerar testes (produção: 64 MiB, t=3).
    "ANDRIPA_ARGON2_MEMORY_KIB": "8192",
    "ANDRIPA_ARGON2_ITERATIONS": "1",
})

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.ratelimit import reset_local  # noqa: E402
from app.core.security import hash_secret, new_public_code  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PG_DSN = TEST_DB.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    with psycopg.connect(PG_DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ})


TABLES = ("audit_logs, order_items, service_requests, orders, customer_tokens, "
          "idempotency_keys, outbox_events, push_subscriptions, notices, product_options, "
          "option_groups, products, categories, staff_sessions, table_sessions, tables, users, establishments")


@pytest.fixture(autouse=True)
def _clean() -> None:
    with psycopg.connect(PG_DSN, autocommit=True) as c:
        c.execute("UPDATE tables SET current_session_id = NULL")
        c.execute(f"TRUNCATE {TABLES} CASCADE")
    import redis
    redis.Redis.from_url(TEST_REDIS).flushdb()
    reset_local()


class _NoJar(http.cookiejar.CookieJar):
    """O cliente de teste não guarda cookies: cada ator envia os seus explicitamente."""

    def extract_cookies(self, response, request) -> None:  # noqa: ANN001
        return None


@pytest.fixture
def app():
    from app.main import create_app
    return create_app(Settings())


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://testserver") as c:
        c.cookies.jar = _NoJar()
        yield c


def pg():
    return psycopg.connect(PG_DSN, autocommit=True)


def make_est(name: str = "Bar Teste") -> uuid.UUID:
    eid = uuid.uuid4()
    with pg() as c:
        c.execute("INSERT INTO establishments (id, name, timezone, orders_enabled) "
                  "VALUES (%s, %s, 'America/Manaus', true)", (eid, name))
    return eid


def make_user(est: uuid.UUID, role: str, username: str | None = None, pin: str | None = None) -> tuple[str, str]:
    """Cria um funcionário e devolve (usuário, PIN)."""
    username = username or f"{role.lower()}-{uuid.uuid4().hex[:6]}"
    pin = pin or f"{uuid.uuid4().int % 10**6:06d}"
    with pg() as c:
        c.execute("INSERT INTO users (id, establishment_id, name, username, role, pin_hash, active) "
                  "VALUES (%s, %s, %s, %s, %s, %s, true)",
                  (uuid.uuid4(), est, f"{role.title()} {username[:4]}", username, role, hash_secret(pin)))
    return username, pin


def make_table(est: uuid.UUID, number: int) -> tuple[str, str]:
    tid, code = uuid.uuid4(), new_public_code()
    with pg() as c:
        c.execute("INSERT INTO tables (id, establishment_id, number, public_code, status, active, version) "
                  "VALUES (%s, %s, %s, %s, 'LIVRE', true, 1)", (tid, est, number, code))
    return str(tid), code


class Actor:
    """Funcionário autenticado: envia o próprio cookie de sessão e o token CSRF."""

    def __init__(self, client: TestClient, username: str, pin: str) -> None:
        self.client = client
        self.username, self.pin = username, pin
        r = client.post("/api/v1/auth/login", json={"username": username, "pin": pin})
        assert r.status_code == 200, r.text
        self.token = r.cookies.get("andripa_staff")
        self.csrf = r.json()["csrf_token"]
        self.me = r.json()

    def headers(self, extra: dict | None = None) -> dict:
        return {"cookie": f"andripa_staff={self.token}", "x-csrf-token": self.csrf, **(extra or {})}

    def get(self, url: str, **kw):
        return self.client.get(url, headers=self.headers(kw.pop("headers", None)), **kw)

    def post(self, url: str, json=None, **kw):  # noqa: A002
        return self.client.post(url, json=json, headers=self.headers(kw.pop("headers", None)), **kw)

    def patch(self, url: str, json=None, **kw):  # noqa: A002
        return self.client.patch(url, json=json, headers=self.headers(kw.pop("headers", None)), **kw)

    def put(self, url: str, json=None, **kw):  # noqa: A002
        return self.client.put(url, json=json, headers=self.headers(kw.pop("headers", None)), **kw)

    def delete(self, url: str, **kw):
        return self.client.delete(url, headers=self.headers(kw.pop("headers", None)), **kw)


class Customer:
    def __init__(self, client: TestClient, code: str) -> None:
        self.client = client
        self.code = code
        r = client.post(f"/api/v1/public/tables/{code}/join")
        assert r.status_code == 200, r.text
        self.token = r.json()["token"]

    def h(self, extra: dict | None = None) -> dict:
        return {"authorization": f"Bearer {self.token}", **(extra or {})}

    def get(self, url: str, **kw):
        return self.client.get(url, headers=self.h(kw.pop("headers", None)), **kw)

    def post(self, url: str, json=None, **kw):  # noqa: A002
        return self.client.post(url, json=json, headers=self.h(kw.pop("headers", None)), **kw)


@pytest.fixture
def world(client):
    """Estabelecimento com admin, caixa, atendente e 3 mesas."""
    est = make_est()
    make_user(est, "ADMIN", "admin", pin="1111")
    make_user(est, "CAIXA", "caixa", pin="2222")
    make_user(est, "ATENDENTE", "atendente", pin="3333")
    tables = [make_table(est, n) for n in (1, 2, 3)]
    return {
        "est": est, "tables": tables,
        "admin": Actor(client, "admin", "1111"), "caixa": Actor(client, "caixa", "2222"),
        "atendente": Actor(client, "atendente", "3333"), "client": client,
    }


def open_table(actor: Actor, table_id: str, key: str | None = None):
    """Liberação pelo painel (funcionário logado)."""
    headers = {"idempotency-key": key} if key else None
    return actor.post(f"/api/v1/tables/{table_id}/open", json={}, headers=headers)


def open_with_pin(client: TestClient, code: str, pin: str):
    """Liberação pela página da mesa: só o PIN."""
    return client.post(f"/api/v1/public/tables/{code}/open", json={"pin": pin})


def close_table(actor: Actor, table_id: str, key: str | None = None):
    headers = {"idempotency-key": key} if key else None
    return actor.post(f"/api/v1/tables/{table_id}/close", json={}, headers=headers)


@pytest.fixture
def menu(world):
    a = world["admin"]
    cat = a.post("/api/v1/menu/categories", json={"name": "Lanches"}).json()
    burger = a.post("/api/v1/menu/products", json={
        "category_id": cat["id"], "name": "X-Burguer", "price_cents": 2500,
        "option_groups": [{"name": "Adicionais", "min_select": 0, "max_select": 2,
                           "options": [{"name": "Bacon", "price_cents": 500}, {"name": "Ovo", "price_cents": 300}]}],
    }).json()
    agua = a.post("/api/v1/menu/products", json={"category_id": cat["id"], "name": "Água", "price_cents": 500}).json()
    return {"category": cat, "burger": burger, "agua": agua}
