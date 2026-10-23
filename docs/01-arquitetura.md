# Andripa — Fase 1: Análise e arquitetura

> Sistema web de atendimento para bares e restaurantes. Este documento é a base técnica do projeto
> e reflete o que foi efetivamente implementado. Diferenças em relação ao documento de requisitos
> (`Ideia.md`) estão justificadas na seção 13 e em `docs/adr/`.

## 1. Resumo funcional

O cliente senta, o atendente **abre a mesa** no painel (confirmando com seu PIN ou senha pessoal).
A partir daí o endereço permanente da mesa (QR Code + tag NFC, ambos para a mesma URL
`https://<dominio>/m/<codigo-publico>`) dá acesso a:

- cardápio real (categorias, produtos, preços, adicionais, indisponibilidade);
- carrinho e envio de pedidos (preço recalculado no servidor);
- **Chamar atendente** e **Pedir a conta**, com estado acompanhado em tempo real;
- promoções e eventos vigentes, validação de cupom e inscrição opcional em notificações push.

Funcionários usam painéis em tempo real (WebSocket): **atendente** (mesas, chamados, pedidos),
**caixa** (tudo do atendente + contas, encerramento, histórico) e **administrador** (tudo +
cardápio, mesas, usuários, promoções, push, auditoria, configurações).

Encerrar a mesa invalida todos os tokens do cliente daquela sessão; a mesa volta a `LIVRE`.

## 2. Arquitetura

```
                 ┌──────────────── CloudFront (HTTPS, ACM) ───────────────┐
 Navegador/PWA ──┤  /*      → S3 (build Vite, SPA, service worker)        │
                 │  /api/*  → ALB (HTTP + WebSocket)                       │
                 └────────────────────────────┬───────────────────────────┘
                                              │
                         ┌────────────────────┴──────────────────┐
                         │ ECS Fargate — N tarefas da API FastAPI │
                         │  • REST /api/v1  • WS /api/v1/ws/*     │
                         │  • relay do outbox (por instância)     │
                         └───────┬───────────────────┬───────────┘
                                 │                   │
                    RDS PostgreSQL (fonte da   ElastiCache Redis
                    verdade + outbox)          (pub/sub de eventos,
                                               rate limiting)
```

Mesma origem para frontend e API (CloudFront roteia `/api/*`), o que elimina CORS em produção e
permite cookies `SameSite=Strict` para funcionários.

### Justificativa das tecnologias
| Camada | Escolha | Por quê |
|---|---|---|
| API | FastAPI + Pydantic v2 | Exigido; contratos tipados e OpenAPI automático |
| ORM | SQLAlchemy 2.x assíncrono + driver psycopg 3 | Exigido; psycopg 3 tem modo async nativo e suporte completo a PostgreSQL |
| Migrações | Alembic | Exigido |
| Tempo real | WebSocket nativo do FastAPI/Starlette | Exigido; sem dependência extra |
| Distribuição de eventos | Transactional outbox no PostgreSQL + Redis Pub/Sub | Pub/Sub sozinho não é durável; o outbox garante que nada se perde |
| Hash de senha | Argon2id (`cryptography`) | Exigido; formato PHC padrão |
| Frontend | React 19 + TypeScript + Vite | Exigido |
| Componentes | Componentes próprios sobre HTML semântico | Ver ADR-0003 |
| PWA | Manifesto + service worker escrito à mão | Controle total da estratégia de cache (ADR-0004) |
| Push | Web Push com VAPID (RFC 8291/8292) implementado sobre `cryptography` + `httpx` | Implementação real, sem serviço terceiro |
| QR Code | `segno` (SVG) | Biblioteca pura em Python, sem dependências |
| IaC | Terraform | Ecossistema maduro, multi-ambiente com `tfvars` |

## 3. Fluxos

### Cliente
1. Lê QR/NFC → `/m/<codigo>` → `GET /public/tables/<codigo>`.
2. Mesa `LIVRE` → mensagem "atendimento digital indisponível", nenhuma ação possível.
3. Mesa ocupada → `POST /public/tables/<codigo>/join` (com código de 4 dígitos se o
   estabelecimento exigir) → recebe **token opaco vinculado à sessão** (não à mesa).
4. Usa cardápio, carrinho, pedidos, chamar atendente, pedir conta — tudo com o token.
5. WebSocket `/ws/customer` autentica com o token na primeira mensagem e recebe atualizações.
6. Mesa encerrada → evento `session.closed` + token passa a responder 401 → tela "sessão encerrada".

### Atendente
Login → painel: mesas (estado, tempo aberta, código de entrada), chamados ordenados por prioridade
e antiguidade, pedidos ativos. Abre mesa (número já cadastrado + nome de identificação + PIN/senha),
assume chamado (exclusivo), inicia/conclui atendimento, atualiza pedidos
(`RECEBIDO → EM_PREPARO → PRONTO → ENTREGUE`).

### Caixa
Tudo do atendente + painel de caixa: mesas com conta solicitada, comanda detalhada, total
calculado no servidor, aplicação de cupom, forma de pagamento (apenas registro), encerramento,
cancelamento de pedidos, priorização manual, histórico de sessões encerradas.

### Administrador
Tudo do caixa + cadastro de mesas (com QR para impressão e URL para gravar na tag NFC),
categorias/produtos/adicionais, usuários e papéis, promoções e cupons, envio de push com
consentimento, auditoria, configurações do estabelecimento.

## 4. Matriz de permissões

Definida em um único lugar: `backend/app/core/permissions.py`. O backend nunca confia no papel
enviado pelo frontend; o papel vem da sessão no banco.

| Permissão | Atendente | Caixa | Admin |
|---|:-:|:-:|:-:|
| `tables.view` ver mesas | ✔ | ✔ | ✔ |
| `tables.open` abrir mesa | ✔ | ✔ | ✔ |
| `tables.request_close` registrar pedido de conta | ✔ | ✔ | ✔ |
| `tables.close` encerrar sessão / liberar mesa | | ✔ | ✔ |
| `tables.manage` cadastrar/editar mesas, QR | | | ✔ |
| `requests.view` / `requests.handle` | ✔ | ✔ | ✔ |
| `requests.prioritize` priorização manual | | ✔ | ✔ |
| `orders.view` / `orders.update_status` | ✔ | ✔ | ✔ |
| `orders.cancel` | | ✔ | ✔ |
| `cash.view` painel de caixa, comanda | | ✔ | ✔ |
| `history.view` histórico de sessões | | ✔ | ✔ |
| `menu.manage` | | | ✔ |
| `promotions.manage` / `push.send` | | | ✔ |
| `users.manage` | | | ✔ |
| `audit.view` | | | ✔ |
| `settings.manage` | | | ✔ |

## 5. Modelo de dados

Todas as chaves primárias são UUID (não enumeráveis), exceto `outbox_events` (bigserial,
usado como cursor ordenado). Datas em UTC (`timestamptz`). Todo registro operacional tem
`establishment_id`, e todas as consultas filtram por ele.

| Entidade | Propósito | Relacionamentos / restrições |
|---|---|---|
| `establishments` | Estabelecimento, fuso horário, configurações | — |
| `users` | Funcionários; `role` ∈ ADMIN/CAIXA/ATENDENTE; hash Argon2id de senha e PIN | e-mail único global |
| `staff_sessions` | Sessões de login (token opaco com hash SHA-256), expiração, revogação | → users |
| `tables` | Mesa física; `number` único por estabelecimento; `public_code` aleatório (128 bits) | → establishments |
| `table_sessions` | Abertura de mesa; `status` OPEN/CLOSED; código de entrada; totais no fechamento | **índice único parcial: 1 sessão aberta por mesa** |
| `customer_tokens` | Tokens do cliente (hash), vinculados à sessão | → table_sessions; revogados no fechamento |
| `service_requests` | Chamados: CHAMAR_ATENDENTE, NOVO_PEDIDO, PEDIR_CONTA | **índice único parcial: 1 chamado ativo por tipo/sessão** (exceto NOVO_PEDIDO) |
| `categories`, `products` | Cardápio; inativação em vez de exclusão | produto → categoria |
| `option_groups`, `product_options` | Adicionais com mínimo/máximo de escolha | → products |
| `orders`, `order_items` | Pedido com snapshot de nome e preço | → table_sessions; itens → products |
| `order_status_history` | Toda mudança de estado de pedido | → orders, users |
| `outbox_events` | Eventos gravados na mesma transação da mudança | publicado → `published_at` |
| `idempotency_keys` | Resposta armazenada por (escopo, chave) | único (scope, key) |
| `push_subscriptions` | Inscrições Web Push com consentimento | endpoint único |
| `promotions` | Banners, eventos, campanhas com período de validade | — |
| `coupons` | Cupons com validade, limite de uso, valor mínimo | código único por estabelecimento |
| `audit_logs` | Ações relevantes (quem, o quê, quando, alvo, detalhes) | — |

Fidelidade (`LoyaltyRecords`) **não** foi implementada nesta entrega — ver limitações.

## 6. Máquinas de estado

```
Mesa:     LIVRE ──abrir──▶ OCUPADA ──pedir conta──▶ ENCERRAMENTO_SOLICITADO
            ▲                 │  ▲                        │
            │                 │  └──cancelar pedido conta─┘
            └──── encerrar (caixa/admin, sem pedidos pendentes ou com política explícita) ◀─┘

Chamado:  PENDENTE ─assumir─▶ ASSUMIDA ─iniciar─▶ EM_ATENDIMENTO ─concluir─▶ CONCLUIDA
             │                   │                                     
             └──cancelar─────────┴──────────────▶ CANCELADA
           (PENDENTE → EM_ATENDIMENTO e PENDENTE → CONCLUIDA também são permitidos ao assumir direto)

Pedido:   RECEBIDO ─▶ EM_PREPARO ─▶ PRONTO ─▶ ENTREGUE
             └──────────┴──── cancelar (caixa/admin) ──▶ CANCELADO
```

O estado `ENCERRANDO` previsto como opcional **não** foi necessário: o encerramento ocorre
inteiro em uma transação com `SELECT … FOR UPDATE` na mesa e na sessão, então não existe estado
intermediário observável (ADR-0002).

Transições são validadas por tabelas de transição em `app/domain/states.py`; qualquer outra
retorna `409 invalid_transition`.

## 7. Autenticação, sessões temporárias e invalidação de links

- **Funcionários**: login com e-mail + senha (Argon2id). O servidor cria `staff_sessions` com
  token aleatório de 256 bits, guarda apenas o SHA-256 e envia o token em cookie
  `HttpOnly; Secure; SameSite=Strict`. Expiração absoluta (12 h) e por inatividade (2 h), logout
  revoga a linha. Proteção CSRF por *double submit*: cookie `andripa_csrf` legível + cabeçalho
  `X-CSRF-Token` obrigatório em métodos que alteram estado.
- **Confirmação na abertura de mesa**: o funcionário reconfirma com seu **PIN pessoal** (se
  configurado) ou sua senha. Validado no servidor contra hash Argon2id. Não há senha compartilhada.
- **Clientes**: o link da mesa só identifica a mesa. `join` gera um token opaco de 256 bits
  vinculado à **sessão** (`table_session_id`), com hash no banco e validade máxima de 12 h. O
  token é enviado como `Authorization: Bearer` (sem cookie → sem CSRF). Toda requisição verifica
  que o token não foi revogado **e** que a sessão continua aberta.
- **Encerramento**: revoga todos os `customer_tokens` da sessão na mesma transação, publica
  `session.closed`, e os WebSockets dessa sessão são fechados com código 4001. Uma página antiga
  aberta recebe 401 em qualquer ação. Um novo cliente na mesma mesa recebe outro token, de outra
  sessão; o token antigo nunca alcança a sessão nova.
- **Código de entrada opcional**: o estabelecimento pode exigir um código de 4 dígitos, gerado na
  abertura e mostrado ao atendente, para evitar uso remoto do link. Tentativas são limitadas.
- **Rotação**: o admin pode gerar novo `public_code` para uma mesa livre (QR comprometido).

## 8. Concorrência, idempotência e entrega de eventos

- **Abertura simultânea**: `SELECT … FOR UPDATE` na mesa + transição condicional + índice único
  parcial `uq_open_session_per_table`. O segundo funcionário recebe `409 table_not_free` com o
  estado atual.
- **Assumir chamado**: `UPDATE … WHERE id = :id AND status = 'PENDENTE' RETURNING` — apenas um
  vence; o outro recebe `409 already_claimed` com o responsável.
- **Idempotência**: cabeçalho `Idempotency-Key` em abrir mesa, criar chamado, criar pedido, pedir
  conta e encerrar. A resposta fica em `idempotency_keys`; repetição devolve a mesma resposta;
  mesma chave com corpo diferente → `422 idempotency_key_reused`.
- **Chamados duplicados**: índice único parcial por (sessão, tipo) enquanto ativo; repetir
  "Chamar atendente" devolve o chamado já ativo. Concluído, um novo chamado é permitido.
- **Versões**: chamados e pedidos têm `version`; eventos carregam o objeto completo com versão;
  a interface só aplica versões maiores (deduplicação natural).
- **Outbox**: toda mudança grava `outbox_events` na mesma transação. Cada instância roda um relay
  (`FOR UPDATE SKIP LOCKED`) que publica no canal Redis `andripa:events` e marca `published_at`.
  Cada instância assina o canal e repassa às conexões locais filtrando por estabelecimento e sessão.
- **Redis indisponível**: o relay entrega diretamente às conexões locais e mantém o evento como
  não publicado; ao voltar, publica (o cliente descarta duplicatas pelo `id`). Rate limiting cai
  para limitador em memória. Nada crítico depende do Redis.
- **Reconexão**: backoff exponencial com jitter (1 s → 30 s). Ao reconectar, o cliente recarrega o
  estado por REST (snapshot) antes de aplicar eventos. Painéis também ressincronizam a cada 30 s.
- **Confirmação**: a API só responde depois do `COMMIT`; a interface só mostra sucesso após a resposta.

## 9. Estrutura de pastas

```
andripa/
├── backend/            FastAPI (app/), Alembic (alembic/), testes (tests/), Dockerfile
│   └── app/
│       ├── api/        rotas por domínio + dependências de auth
│       ├── core/       config, segurança, permissões, erros, logs, rate limit
│       ├── db/         engine, sessão, base
│       ├── domain/     máquinas de estado
│       ├── models/     modelos SQLAlchemy
│       ├── schemas/    contratos Pydantic
│       ├── services/   regras de negócio (mesas, chamados, pedidos, cardápio, push…)
│       └── realtime/   outbox relay, broker Redis, gerenciador de conexões
├── frontend/           React + TS + Vite, PWA (public/sw.js, manifest), testes e2e Playwright
├── infra/terraform/    AWS (VPC, ECS Fargate, ALB, RDS, ElastiCache, S3, CloudFront, Secrets, CloudWatch)
├── docs/               arquitetura, ADRs, guias, relatórios
├── docker-compose.yml  desenvolvimento local
└── .github/workflows/  CI/CD
```

## 10. Plano de entregas

| Fase | Entrega testável |
|---|---|
| 1 | Este documento + ADRs |
| 2 | API sobe, migração aplica, login/logout/me, RBAC com testes |
| 3 | Mesas, abertura/encerramento, QR/NFC, tokens de cliente, revogação, concorrência |
| 4 | Chamados, outbox, WebSocket staff/cliente, painéis com reconexão |
| 5 | Cardápio (admin), cardápio do cliente, carrinho, pedidos e estados |
| 6 | PWA instalável, Web Push, promoções e cupons |
| 7 | Docker, Terraform, CI/CD, docs operacionais, relatório de testes |

## 11. Critérios de aceitação por fase
- F2: `pytest tests/test_auth.py tests/test_permissions.py` verde contra PostgreSQL real.
- F3: abrir mesa ocupada → 409; abertura concorrente gera exatamente 1 sessão; token antigo → 401.
- F4: chamado aparece via WebSocket em outra instância (via Redis); reconexão recupera estado.
- F5: preço manipulado no corpo é ignorado; pedido em sessão encerrada → 401.
- F6: manifesto válido, SW registrado; criptografia Web Push validada com o vetor da RFC 8291.
- F7: cenários A–J do documento de requisitos demonstrados (ver `docs/10-relatorio-testes.md`).

## 12. Riscos e mitigação
| Risco | Mitigação |
|---|---|
| Perda de eventos entre DB e WebSocket | Outbox transacional + snapshot REST na reconexão |
| Abuso do link público | Token por sessão, código de entrada opcional, rate limit por IP e por sessão |
| Escala horizontal com WebSocket | Redis Pub/Sub; ALB com stickiness desnecessária |
| Redis fora do ar | Degradação controlada documentada e testada |
| Push não suportado (iOS sem PWA instalado etc.) | Recurso opcional; atendimento não depende dele |
| Corrida em operações críticas | Locks de linha, updates condicionais, índices únicos parciais, idempotência |
| Vazamento de dados entre estabelecimentos | `establishment_id` obrigatório em todas as consultas + testes dedicados |

## 13. Decisões que divergem do texto de requisitos
- **Roles/Permissions** em código, não em tabelas (ADR-0001): três papéis fixos são o requisito;
  tabela de permissões dinâmicas aumentaria a superfície de erro sem benefício atual.
- **Estado ENCERRANDO** não usado (ADR-0002).
- **Biblioteca de componentes**: componentes próprios acessíveis (ADR-0003).
- **Fidelidade**: estrutura documentada, não implementada (sem botões na interface).
