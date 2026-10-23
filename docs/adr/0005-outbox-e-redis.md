# ADR-0005 — Transactional outbox + Redis Pub/Sub

**Contexto.** Eventos em tempo real precisam ser consistentes com o banco e funcionar com várias instâncias da API.
**Decisão.** Cada mudança grava uma linha em `outbox_events` na mesma transação. Um relay por instância lê pendentes com `FOR UPDATE SKIP LOCKED`, publica no canal Redis `andripa:events` e marca `published_at`; cada instância assina o canal e repassa às suas conexões. Clientes deduplicam por `id` e aplicam só `version` maior; a cada reconexão recarregam o estado por REST.
**Sem Redis.** O relay entrega localmente e deixa o evento pendente; como todas as instâncias leem o outbox, todas entregam às suas conexões (testado em `test_realtime_degraded.py`). Quando o Redis volta, os pendentes são publicados.
**Consequências.** Entrega *at-least-once* com deduplicação no cliente. O relay pode ser movido para um processo dedicado com `ANDRIPA_RELAY_ENABLED=false` nas instâncias web.
