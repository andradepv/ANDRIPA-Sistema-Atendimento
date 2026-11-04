# API e contratos

- Base: `/api/v1`. Contrato completo gerado pelo FastAPI em `docs/openapi.json` (também em
  `/api/v1/docs` fora de produção).
- JSON em UTF-8; datas em ISO 8601 **UTC**.
- Corpos com campos desconhecidos são rejeitados (`extra="forbid"`): não dá para enviar
  `session_id` ou `table_id` para “apontar” outro recurso.
- Limite de corpo: 64 KiB (`413 payload_too_large`).

## Autenticação
| Quem | Como |
|---|---|
| Funcionário | `POST /auth/login` → cookie `andripa_staff` (HttpOnly, Secure, SameSite=Strict, path `/api`) + cookie `andripa_csrf`. Métodos de escrita exigem o cabeçalho `X-CSRF-Token` com o valor do cookie. |
| Cliente da mesa | `POST /public/tables/{codigo}/join` → `{token}`. Enviar `Authorization: Bearer <token>`. O token vale só para aquela sessão e é revogado no encerramento. |

## Formato de erro
```json
{ "error": { "code": "table_not_free", "message": "A mesa 4 já está aberta.", "details": { "status": "OCUPADA" } } }
```
Códigos estáveis usados pela interface: `unauthenticated`, `session_ended`, `forbidden`, `csrf_failed`,
`confirmation_failed`, `validation_error`, `not_found`, `table_not_free`, `table_not_open`,
`already_claimed`, `invalid_transition`, `stale_version`,
`idempotency_key_reused`, `rate_limited`, `payload_too_large`.

## Idempotência
Envie `Idempotency-Key: <8–80 caracteres [A-Za-z0-9_-:.]>` em: abrir mesa, criar chamado,
encerrar mesa. A primeira resposta é gravada na mesma transação; repetições recebem a mesma resposta com
`Idempotent-Replay: true`. Mesma chave com outro corpo → `422 idempotency_key_reused`. Erros não são
gravados (uma nova tentativa executa de novo).

**Repetição automática segura**: GETs; POSTs com `Idempotency-Key` (a interface reutiliza a chave quando
a falha foi de rede). **Exige confirmação do usuário**: encerrar a mesa após erro de versão
(`stale_version`), gerar novo endereço de mesa.

## Endpoints (resumo)
| Método e caminho | Permissão | Descrição |
|---|---|---|
| `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /auth/me`, `POST /auth/credentials` | — / sessão | Sessão do funcionário, troca de senha/PIN |
| `GET /tables` · `POST /tables` · `PATCH /tables/{id}` | view · manage | Mesas (com resumo da sessão) |
| `GET /tables/{id}/qr.svg` · `POST /tables/{id}/rotate-code` | manage | QR Code e novo endereço |
| `POST /tables/{id}/open` | tables.open | Abre a mesa (`label`, `confirm_secret`) |
| `POST /tables/{id}/request-close` · `/cancel-close-request` | request_close · close | Pedido de conta |
| `GET /table-sessions/{id}` · `POST /table-sessions/{id}/close` | view · close | Detalhe da sessão (com chamados) e encerramento |
| `GET /table-sessions?status=CLOSED&table_number=&limit=&offset=` | history.view | Histórico paginado |
| `GET /service-requests?active=true` | requests.view | Fila ordenada por estado, prioridade e antiguidade |
| `POST /service-requests/{id}/claim · start · complete · cancel · priority` | handle / prioritize | Fluxo do chamado |
| `GET/PATCH /admin/establishment`, `GET/POST/PATCH /admin/users`, `GET /admin/audit-logs` | admin | Administração |
| `POST /admin/tables/provision` | tables.provision | Cria mesa (endereço, QR, posição na planta) e abre a gravação da etiqueta (`number`, `name`, `confirm_secret`) |
| `POST /admin/tables/{id}/tag` (`replace`) · `GET /admin/tags` | tables.provision | Inicia/refaz a gravação de uma mesa; lista gravações em andamento e recentes |
| `POST /admin/tags/{id}/writing · written · failed · authorize-lock · locked` | tables.provision | Ciclo da etiqueta (ver docs/11) |
| `GET /layouts/active` | tables.view | Planta ativa do salão (todos os painéis) |
| `GET/POST /admin/layouts` · `PATCH/DELETE /admin/layouts/{id}` · `PUT .../items` · `POST .../activate` | layouts.manage | Plantas (templates) do salão |
| `GET /public/tables/{codigo}` · `POST /public/tables/{codigo}/join` | público (rate limit) | Mesa e entrada |
| `GET /public/session` | token da mesa | Estado da mesa e chamados |
| `POST /public/service-requests` · `/{id}/cancel` | token da mesa | Chamar o atendente, pedir a conta, cancelar chamado pendente |
| `GET /health/live` · `GET /health/ready` | — | Saúde (ready = banco ok; Redis fora = `degraded`) |

## WebSocket
- `/api/v1/ws/staff`: autenticado pelo cookie; `Origin` precisa estar em `ANDRIPA_ALLOWED_ORIGINS`.
- `/api/v1/ws/customer`: a primeira mensagem deve ser `{"type":"auth","token":"..."}` em até 5 s
  (o token nunca vai na URL).
- Servidor envia `{"type":"hello"}` ao aceitar. A cada (re)conexão o cliente **recarrega o estado por REST**.
- Heartbeat: servidor envia `ping` a cada 25 s; o cliente envia `ping` a cada 20 s. Sem tráfego por 75 s →
  fechamento. A sessão é revalidada a cada 60 s.
- Eventos: `{"id": <inteiro crescente>, "type": "...", "data": {...}}` com tipos `table.updated`,
  `request.updated`, `session.closed`,
  `settings.updated`, `tag.updated` (gravação de etiqueta), `layout.updated` (planta ativa). Entidades trazem `version`; aplique só versões maiores e ignore `id` repetido.
- Códigos de fechamento: `4001` sessão da mesa encerrada, `4003` não autorizado (handshake recusado com
  HTTP 403 quando a falha é na abertura), `1013` cliente lento.
