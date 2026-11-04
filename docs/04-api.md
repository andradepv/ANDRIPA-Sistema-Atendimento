# API e contratos

- Base: `/api/v1`. Contrato completo gerado pelo FastAPI em `docs/openapi.json` (também em
  `/api/v1/docs` fora de produção).
- JSON em UTF-8; datas em ISO 8601 **UTC**; valores em **centavos** (inteiros).
- Corpos com campos desconhecidos são rejeitados (`extra="forbid"`): não dá para enviar `price_cents`,
  `session_id` ou `table_id` para “apontar” outro recurso.
- Limite de corpo: 64 KiB (`413 payload_too_large`).

## Autenticação
| Quem | Como |
|---|---|
| Funcionário (painel) | `POST /auth/login {username, pin}` → cookie `andripa_staff` (HttpOnly, Secure, SameSite=Strict, path `/api`) + cookie `andripa_csrf`. Métodos de escrita exigem o cabeçalho `X-CSRF-Token` com o valor do cookie. |
| Atendente (página da mesa) | `POST /public/tables/{codigo}/open {pin}` libera a mesa sem login. |
| Cliente da mesa | `POST /public/tables/{codigo}/join` → `{token}`. Enviar `Authorization: Bearer <token>`. O token vale só para aquela sessão e é revogado quando a conta é finalizada. |

## Formato de erro
```json
{ "error": { "code": "table_not_free", "message": "A mesa 4 já está liberada.", "details": {} } }
```
Códigos estáveis usados pela interface: `unauthenticated`, `invalid_credentials`, `invalid_pin`,
`session_ended`, `forbidden`, `csrf_failed`, `confirmation_failed`, `validation_error`, `not_found`,
`table_not_free`, `table_not_open`, `already_done`, `pin_taken`, `username_taken`, `orders_disabled`,
`idempotency_key_reused`, `rate_limited`, `payload_too_large`, `push_disabled`.

## Idempotência
Envie `Idempotency-Key: <8–80 caracteres [A-Za-z0-9_-:.]>` em: liberar mesa (painel), criar chamado, criar
pedido, finalizar conta. A primeira resposta é gravada na mesma transação; repetições recebem a mesma
resposta com `Idempotent-Replay: true`. Mesma chave com outro corpo → `422 idempotency_key_reused`.

## Endpoints (resumo)
| Método e caminho | Permissão | Descrição |
|---|---|---|
| `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /auth/me`, `POST /auth/pin` | — / sessão | Sessão do funcionário e troca do próprio PIN |
| `GET /tables` · `POST /tables` · `PATCH /tables/{id}` | view · manage | Mesas (com contadores de chamados, pedidos e conta pedida) |
| `GET /tables/{id}/qr.svg` · `POST /tables/{id}/rotate-code` | manage | QR Code e novo endereço |
| `POST /tables/{id}/open` | tables.open | Libera a mesa pelo painel |
| `POST /tables/{id}/close` | tables.close | Conta finalizada: encerra o atendimento e libera a mesa |
| `GET /service-requests` | tables.view | Solicitações aguardando (mais antigas primeiro), pedidos com itens |
| `POST /service-requests/{id}/complete` | requests.handle (conta: tables.close) | Atendido / repassado à cozinha / conta finalizada |
| `GET /table-sessions/{id}` | tables.view (encerradas: history.view) | Atendimento com todas as solicitações e horários |
| `GET /table-sessions?table_id=&limit=&offset=` | history.view | Atendimentos anteriores |
| `GET/POST/PATCH /menu/categories`, `/menu/products` | leitura: sessão · escrita: menu.manage | Cardápio |
| `GET/PATCH /admin/establishment`, `GET/POST/PATCH /admin/users`, `GET /admin/audit-logs` | admin | Administração |
| `GET/POST /admin/notices` · `PATCH/DELETE /admin/notices/{id}` · `GET /admin/push/stats` | notices.manage | Avisos aos clientes (push opcional) |
| `GET /public/tables/{codigo}` · `POST /public/tables/{codigo}/open` · `/join` | público (rate limit) | Página da mesa, liberar com PIN, entrar como cliente |
| `GET /public/session` · `GET /public/menu` · `GET /public/notices` | token da mesa | Acompanhamento, cardápio, novidades |
| `POST /public/service-requests` · `/{id}/cancel` · `POST /public/orders` | token da mesa | Chamar atendente, pedir a conta, fazer pedido |
| `GET /public/push/config` · `POST /public/push/subscribe` · `/unsubscribe` | token / público | Web Push |
| `GET /health/live` · `GET /health/ready` | — | Saúde (ready = banco ok; Redis fora = `degraded`) |

## WebSocket
- `/api/v1/ws/staff`: autenticado pelo cookie; `Origin` precisa estar em `ANDRIPA_ALLOWED_ORIGINS`.
- `/api/v1/ws/customer`: a primeira mensagem deve ser `{"type":"auth","token":"..."}` em até 5 s
  (o token nunca vai na URL).
- Servidor envia `{"type":"hello"}` ao aceitar. A cada (re)conexão o cliente **recarrega o estado por REST**.
- Heartbeat: servidor envia `ping` a cada 25 s; o cliente envia `ping` a cada 20 s. Sem tráfego por 75 s →
  fechamento. A sessão é revalidada a cada 60 s.
- Eventos: `{"id": <inteiro crescente>, "type": "...", "data": {...}}` com tipos `table.updated`,
  `request.updated`, `session.closed`, `menu.updated`, `notices.updated`, `settings.updated`.
  Entidades trazem `version`; aplique só versões maiores e ignore `id` repetido.
- Códigos de fechamento: `4001` sessão da mesa encerrada, `4003` não autorizado (handshake recusado com
  HTTP 403 quando a falha é na abertura), `1013` cliente lento.
