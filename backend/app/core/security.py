from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

# Parâmetros Argon2id (RFC 9106, perfil de memória reduzida: m=64 MiB, t=3, p=4).
_ARGON_MEMORY_KIB = int(os.environ.get("ANDRIPA_ARGON2_MEMORY_KIB", 64 * 1024))
_ARGON_ITERATIONS = int(os.environ.get("ANDRIPA_ARGON2_ITERATIONS", 3))
_ARGON_LANES = 4


def hash_secret(secret: str) -> str:
    """Gera hash Argon2id no formato PHC ($argon2id$v=19$m=...,t=...,p=...$salt$hash)."""
    kdf = Argon2id(
        salt=os.urandom(16),
        length=32,
        iterations=_ARGON_ITERATIONS,
        lanes=_ARGON_LANES,
        memory_cost=_ARGON_MEMORY_KIB,
    )
    return kdf.derive_phc_encoded(secret.encode("utf-8"))


def verify_secret(secret: str, encoded: str | None) -> bool:
    if not encoded:
        # Executa um hash de qualquer forma para reduzir diferença de tempo.
        _DUMMY_VERIFY(secret)
        return False
    try:
        Argon2id.verify_phc_encoded(secret.encode("utf-8"), encoded)
        return True
    except (InvalidKey, ValueError):
        return False


_DUMMY_HASH: str | None = None


def _DUMMY_VERIFY(secret: str) -> None:  # noqa: N802
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_secret("dummy-password-for-timing")
    try:
        Argon2id.verify_phc_encoded(secret.encode("utf-8"), _DUMMY_HASH)
    except (InvalidKey, ValueError):
        pass


def new_token() -> str:
    """Token opaco de 256 bits, seguro para URL."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_public_code() -> str:
    """Código público da mesa (128 bits) — impossível de adivinhar por enumeração."""
    return secrets.token_urlsafe(16)


def new_join_code() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
