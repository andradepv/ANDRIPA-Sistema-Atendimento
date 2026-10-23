"""Web Push real: criptografia de mensagem (RFC 8291, aes128gcm) e VAPID (RFC 8292).

Implementado sobre `cryptography` para evitar dependências extras. Validado contra o vetor
de teste da RFC 8291 (tests/test_webpush.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64u_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _pub_bytes(pub: ec.EllipticCurvePublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt(
    plaintext: bytes,
    ua_public_b64: str,
    auth_secret_b64: str,
    *,
    as_private: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
    record_size: int = 4096,
) -> bytes:
    ua_public = b64u_decode(ua_public_b64)
    auth_secret = b64u_decode(auth_secret_b64)
    if len(ua_public) != 65 or len(auth_secret) != 16:
        raise ValueError("Chaves de inscrição inválidas")
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _pub_bytes(as_private.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = as_private.exchange(ec.ECDH(), ua_key)

    prk_key = _hmac(auth_secret, ecdh_secret)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]

    if len(plaintext) + 1 + 16 > record_size:
        raise ValueError("Mensagem grande demais para um registro")
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + struct.pack("!I", record_size) + bytes([len(as_public)]) + as_public
    return header + ciphertext


def decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth_secret_b64: str) -> bytes:
    """Lado do navegador — usado apenas nos testes."""
    salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_public = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    assert rs >= 18
    ua_public = _pub_bytes(ua_private.public_key())
    as_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    ecdh_secret = ua_private.exchange(ec.ECDH(), as_key)
    auth_secret = b64u_decode(auth_secret_b64)
    prk_key = _hmac(auth_secret, ecdh_secret)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return padded.rstrip(b"\x00")[:-1]


def load_vapid_private(value: str) -> ec.EllipticCurvePrivateKey:
    value = value.strip()
    if value.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(value.encode(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
    return ec.derive_private_key(int.from_bytes(b64u_decode(value), "big"), ec.SECP256R1())


def generate_vapid_keys() -> tuple[str, str]:
    k = ec.generate_private_key(ec.SECP256R1())
    priv = k.private_numbers().private_value.to_bytes(32, "big")
    return b64u_encode(_pub_bytes(k.public_key())), b64u_encode(priv)


def vapid_header(endpoint: str, private_key: ec.EllipticCurvePrivateKey, public_key_b64: str,
                 subject: str, ttl_seconds: int = 12 * 3600) -> str:
    parts = urlsplit(endpoint)
    aud = f"{parts.scheme}://{parts.netloc}"
    header = b64u_encode(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u_encode(json.dumps({"aud": aud, "exp": int(time.time()) + ttl_seconds, "sub": subject},
                                    separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    der = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = b64u_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{sig}, k={public_key_b64}"
