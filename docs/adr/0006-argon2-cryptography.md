# ADR-0006 — Argon2id via `cryptography`

**Decisão.** Hash de senhas e PINs com `cryptography.hazmat.primitives.kdf.argon2.Argon2id` (formato PHC, m=64 MiB, t=3, p=4 — RFC 9106), em vez de `argon2-cffi`.
**Por quê.** `cryptography` já é necessária (Web Push, VAPID) e mantida pela PyCA; evita uma dependência nativa adicional.
**Consequências.** Requer `cryptography>=46`. Os hashes PHC são compatíveis com outras implementações Argon2id caso seja preciso migrar.
