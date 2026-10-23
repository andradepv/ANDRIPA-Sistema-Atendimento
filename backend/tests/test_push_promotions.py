from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import Customer, open_table, pg
from cryptography.hazmat.primitives import serialization

from app.services import webpush

# Vetor de teste oficial — RFC 8291, seção 5.
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEq"
            "KK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def test_webpush_rfc8291_vector():
    body = webpush.encrypt(RFC["plaintext"], RFC["ua_public"], RFC["auth"],
                           as_private=webpush.load_vapid_private(RFC["as_private"]),
                           salt=webpush.b64u_decode(RFC["salt"]))
    assert webpush.b64u_encode(body) == RFC["body"]
    assert webpush.decrypt(body, webpush.load_vapid_private(RFC["ua_private"]), RFC["auth"]) == RFC["plaintext"]


def test_vapid_jwt_signature_valid():
    import base64
    import json

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    pub, priv = webpush.generate_vapid_keys()
    h = webpush.vapid_header("https://push.example.com/abc", webpush.load_vapid_private(priv), pub, "mailto:a@b.c")
    token = h.split("t=")[1].split(",")[0]
    head, claims, sig = token.split(".")
    assert json.loads(webpush.b64u_decode(claims))["aud"] == "https://push.example.com"
    raw = webpush.b64u_decode(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64u_decode(pub))
    key.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # não lança = válido
    assert base64  # noqa: B018


@pytest.fixture
def push_enabled(monkeypatch):
    pub, priv = webpush.generate_vapid_keys()
    from app.core import config
    s = config.get_settings()
    monkeypatch.setattr(s, "vapid_public_key", pub)
    monkeypatch.setattr(s, "vapid_private_key", priv)
    return s


def _browser_subscription():
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    import os
    auth = os.urandom(16)
    return k, webpush.b64u_encode(pub), webpush.b64u_encode(auth)


def test_push_disabled_by_default(client, world):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    assert client.get("/api/v1/public/push/config").json() == {"enabled": False, "public_key": None}
    r = c.post("/api/v1/public/push/subscribe", json={
        "subscription": {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "a", "auth": "b"}},
        "consent_marketing": True})
    assert r.status_code == 503


def test_push_subscribe_requires_consent_and_broadcast(client, world, push_enabled):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    c = Customer(client, code)
    k, p256dh, auth = _browser_subscription()
    sub = {"endpoint": "https://push.example.com/send/abc", "keys": {"p256dh": p256dh, "auth": auth}}
    assert c.post("/api/v1/public/push/subscribe", json={"subscription": sub, "consent_marketing": False}).status_code == 422
    assert c.post("/api/v1/public/push/subscribe", json={"subscription": sub, "consent_marketing": True}).status_code == 204
    gone = {"endpoint": "https://push.example.com/send/gone", "keys": {"p256dh": p256dh, "auth": auth}}
    assert c.post("/api/v1/public/push/subscribe", json={"subscription": gone, "consent_marketing": True}).status_code == 204
    assert world["admin"].get("/api/v1/admin/push/stats").json() == {"enabled": True, "subscribers": 2}

    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-encoding"] == "aes128gcm"
        assert request.headers["authorization"].startswith("vapid t=")
        if request.url.path.endswith("gone"):
            return httpx.Response(410)
        received.append(webpush.decrypt(request.content, k, auth))
        return httpx.Response(201)

    import asyncio

    from app.db.session import db as appdb
    from app.schemas import PushBroadcastIn
    from app.services import push as push_svc

    async def run():
        from app.core.config import get_settings
        appdb.init(get_settings().database_url, null_pool=True)
        est = world["est"]
        async with appdb.session() as s, httpx.AsyncClient(transport=httpx.MockTransport(handler)) as hc:
            return await push_svc.broadcast(s, est, PushBroadcastIn(title="Happy hour", body="Chopp em dobro"), client=hc)

    out = asyncio.run(run())
    assert (out.targeted, out.sent, out.removed) == (2, 1, 1)
    assert b"Happy hour" in received[0]
    # A inscrição que respondeu 410 foi removida; cancelamento manual também funciona.
    assert client.post("/api/v1/public/push/unsubscribe", json={"endpoint": sub["endpoint"]}).status_code == 204
    with pg() as cn:
        active = cn.execute("SELECT count(*) FROM push_subscriptions WHERE revoked_at IS NULL").fetchone()[0]
    assert active == 0


def _iso(dt):
    return dt.isoformat()


def test_promotions_only_within_period(client, world):
    now = datetime.now(UTC)
    a = world["admin"]
    assert a.post("/api/v1/admin/promotions", json={"kind": "BANNER", "title": "Vigente",
                                                    "starts_at": _iso(now - timedelta(hours=1)),
                                                    "ends_at": _iso(now + timedelta(hours=1))}).status_code == 201
    a.post("/api/v1/admin/promotions", json={"kind": "EVENTO", "title": "Futuro",
                                             "starts_at": _iso(now + timedelta(days=1)),
                                             "ends_at": _iso(now + timedelta(days=2))})
    a.post("/api/v1/admin/promotions", json={"kind": "CAMPANHA", "title": "Inativa", "active": False,
                                             "starts_at": _iso(now - timedelta(hours=1)),
                                             "ends_at": _iso(now + timedelta(hours=1))})
    assert a.post("/api/v1/admin/promotions", json={"kind": "BANNER", "title": "Inválida",
                                                    "starts_at": _iso(now), "ends_at": _iso(now)}).status_code == 422
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    promos = Customer(client, code).get("/api/v1/public/promotions").json()
    assert [p["title"] for p in promos] == ["Vigente"]


def test_coupon_validate_and_redeem_limits(client, world, menu):
    now = datetime.now(UTC)
    a = world["admin"]
    base = {"discount_type": "PERCENT", "value": 10, "starts_at": _iso(now - timedelta(hours=1)),
            "ends_at": _iso(now + timedelta(hours=1))}
    assert a.post("/api/v1/admin/coupons", json={**base, "code": "dez", "max_uses": 1}).status_code == 201
    assert a.post("/api/v1/admin/coupons", json={**base, "code": "DEZ"}).status_code == 409
    assert a.post("/api/v1/admin/coupons", json={**base, "code": "MUITO", "value": 150}).status_code == 422
    a.post("/api/v1/admin/coupons", json={**base, "code": "VELHO", "starts_at": _iso(now - timedelta(days=2)),
                                          "ends_at": _iso(now - timedelta(days=1))})

    (t1, c1), (t2, c2) = world["tables"][0], world["tables"][1]
    open_table(world["atendente"], t1)
    open_table(world["atendente"], t2)
    x, y = Customer(client, c1), Customer(client, c2)
    o = x.post("/api/v1/public/orders", json={"items": [{"product_id": menu["burger"]["id"], "quantity": 2}]}).json()
    v = x.post("/api/v1/public/coupons/validate", json={"code": "dez"}).json()
    assert v["valid"] is True and v["estimated_discount_cents"] == 500
    assert x.post("/api/v1/public/coupons/validate", json={"code": "VELHO"}).json()["reason"] == "Cupom expirado."
    assert x.post("/api/v1/public/coupons/validate", json={"code": "NAOEXISTE"}).json()["valid"] is False

    world["atendente"].post(f"/api/v1/orders/{o['id']}/status", json={"status": "ENTREGUE"})
    r = world["caixa"].post(f"/api/v1/table-sessions/{o['session_id']}/close",
                            json={"payment_method": "PIX", "coupon_code": "DEZ"})
    assert r.status_code == 200 and r.json()["discount_cents"] == 500 and r.json()["total_cents"] == 4500
    # Limite de uso: segundo uso falha e a mesa continua aberta.
    sid2 = y.get("/api/v1/public/session").json()["session_id"]
    r2 = world["caixa"].post(f"/api/v1/table-sessions/{sid2}/close", json={"payment_method": "PIX", "coupon_code": "DEZ"})
    assert r2.status_code == 422 and r2.json()["error"]["code"] == "coupon_invalid"
    assert y.get("/api/v1/public/session").status_code == 200
