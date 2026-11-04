# Relatório de testes — resultados reais

Execução de 2/11/2026 sobre a versão **restrita a chamado de garçom e gestão de mesas** (sem cardápio,
pedidos, cupons, promoções, push e valores da conta). Ambiente: Linux, **PostgreSQL 16 e Redis 7 reais**.
Só está aqui o que foi executado; o que não foi, está na seção 5.

## 1. Backend — `pytest` (86 testes, 0 falhas, ~53 s)

| Arquivo | Testes | O que cobre |
|---|--:|---|
| `test_auth.py` | 9 | Login/logout, flags do cookie, senha errada, usuário inativo, CSRF, rate limit de login, revogação ao trocar papel, último admin, troca de PIN |
| `test_permissions.py` | 21 | Matriz RBAC (funções admin × atendente/caixa), escalonamento de privilégio, caixa × atendente, acesso sem autenticação, **isolamento entre estabelecimentos** |
| `test_tables.py` | 10 | Abertura, mesa ocupada → 409, confirmação individual (PIN/senha), idempotência, **9 aberturas simultâneas → 1 sessão**, QR SVG, rotação de código, encerramento e revogação de tokens, token antigo × sessão nova |
| `test_customer.py` | 10 | Mesa livre bloqueada, códigos adivinhados, nenhum ID interno exposto, chamar atendente e deduplicação, **12 chamados concorrentes → 1 registro**, Idempotency-Key, cancelamento, cliente não toca outra mesa, código de entrada + força bruta, rate limit |
| `test_requests.py` | 5 | **5 funcionários assumindo o mesmo chamado → 1 responsável**, só o responsável/supervisor conclui, prioridade e ordenação, conta concluída só pelo caixa, persistência após recarregar |
| `test_realtime.py` | 6 | **Duas instâncias reais (uvicorn)**: entrega entre instâncias via Redis, sem duplicatas, WebSocket do cliente recebe a atualização do chamado e é encerrado com 4001 no fechamento, autorização do WebSocket, logout derruba o painel, **reconexão recupera estado** |
| `test_realtime_degraded.py` | 1 | **Redis inacessível**: health "degraded", chamado persistido e entregue nas duas instâncias via outbox, rate limit local ativo |
| `test_security.py` | 9 | Limite de corpo (413), UUID/JSON inválidos, SQL injection tratada como dado, cabeçalhos de segurança, CORS restrito, tokens forjados, senhas nunca em texto puro (Argon2id), trilha de auditoria, health |
| `test_tags_layouts.py` | 15 | Etiquetas NFC (ciclo, URL conferida, mesma etiqueta em duas mesas), plantas do salão, concorrência e permissões |

Em relação à versão anterior (102 testes), saíram os 16 que cobriam pedidos, cardápio, push, promoções e cupons
(`test_orders.py`, `test_push_promotions.py`); os demais foram adaptados ao escopo menor.

## 2. Migração de dados
A revisão `0003` remove as tabelas e colunas de venda. Foi aplicada sobre um banco de teste que **continha
pedidos, chamados `NOVO_PEDIDO` e valores de sessão**: os chamados de pedido foram apagados, as tabelas e
colunas removidas e `alembic check` não acusou divergência entre modelos e esquema. O `downgrade` é
propositalmente indisponível (a remoção de dados não é reversível; restaure um backup).

## 3. Execução real da aplicação
Com API no ar (uvicorn, PostgreSQL e Redis reais) e `seed-dev`: atendente abre mesa → cliente entra pela URL →
chama o atendente (201) → atendente assume (`ASSUMIDA`) → cliente pede a conta (mesa vai a
`ENCERRAMENTO_SOLICITADO`) → caixa encerra → o token do cliente passa a responder 401. Chamado do tipo
`NOVO_PEDIDO` → 422; `/public/menu`, `/public/promotions`, `/orders` e `/admin/promotions` → 404.

**Carga** (`backend/scripts/loadtest.py`, 20 clientes por 15 s, 1 processo uvicorn, ambiente de desenvolvimento,
111,9 req/s, 0 erros):

| Endpoint | Requisições | p50 | p95 | p99 |
|---|--:|--:|--:|--:|
| GET /tables | 559 | 190,0 ms | 265,9 ms | 492,9 ms |
| GET /service-requests | 558 | 141,3 ms | 207,3 ms | 410,6 ms |
| GET /public/session | 562 | 166,5 ms | 231,6 ms | 423,5 ms |

Meta de referência: p95 < 500 ms. Repita a medição em homologação antes de fixar metas definitivas.

## 4. Qualidade estática e build

| Verificação | Resultado |
|---|---|
| `ruff check app tests` | só os 8 avisos de estilo UP042/UP046 (herdados) |
| `mypy app` | 0 problemas em 41 arquivos |
| `bandit -r app` | 0 alto, 0 médio, 9 baixos |
| `tsc --noEmit` (strict) | 0 erros |
| `vite build` | OK — JS 288 kB (89 kB gzip), CSS 18 kB |
| `alembic upgrade head` + `alembic check` | sem divergência entre modelos e migrações |

## 5. O que NÃO foi executado nesta versão
- **Testes ponta a ponta no navegador (Playwright)**: o ambiente não conseguiu baixar o Chromium. Os arquivos
  `frontend/e2e/*.spec.ts` foram **ajustados ao novo fluxo, mas não rodados**.
- `pip-audit`, `npm audit`, `docker build`, `terraform validate/plan` e o script de backup/restauração
  (`infra/scripts/backup_restore_test.sh`, ajustado para as tabelas atuais).
- Testes em Firefox/Safari e em etiquetas NFC reais; NFC é só uma etiqueta passiva com a mesma URL do QR.
