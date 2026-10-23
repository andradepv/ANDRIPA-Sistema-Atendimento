# ADR-0001 — Papéis e permissões definidos em código

**Contexto.** O requisito tem três papéis fixos (Administrador, Caixa, Atendente) com permissões bem definidas.
**Decisão.** `users.role` é um enum no banco; o mapa papel → permissões fica em `app/core/permissions.py`, e cada rota declara a permissão exigida.
**Consequências.** Uma única fonte de verdade, revisável em PR e coberta por testes. Criar um papel novo exige deploy. Se surgir a necessidade de papéis configuráveis por estabelecimento, migrar para tabelas `roles`/`role_permissions` mantendo os mesmos nomes de permissão.
