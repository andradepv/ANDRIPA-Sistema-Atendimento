# Relatório de testes — resultados reais

## MVP simplificado — execução de 04/11/2026

Windows 11 + Docker (PostgreSQL 16, Redis 7, Python 3.13), **banco e Redis reais**. Ver
[ADR-0007](adr/0007-mvp-simplificado.md) para o que mudou.

| Verificação | Resultado |
|---|---|
| `pytest` (88 testes) | **88 passaram, 0 falhas** (~52 s) |
| Testes de concorrência e tempo real repetidos 5× (liberação simultânea painel × PIN, toque duplo em “Atendido”, pedido × encerramento, entrega entre instâncias) | **5/5 verdes** |
| Playwright/Chromium (4 testes) | **4 passaram**: jornada completa, atendente só vê o Salão, avisos em Novidades com navegador sem Push, endereço inexistente |
| `ruff check app tests` · `mypy app` · `tsc --noEmit` · `vite build` | 0 problemas · 0 problemas · 0 erros · OK |
| `alembic upgrade → downgrade base → upgrade` + `alembic check` | sem divergência |
| Carga (20 clientes, 30 s, 1 processo) | **196 req/s, 0 erros**, p95 entre 126 e 193 ms |

| Endpoint | Requisições | p50 | p95 | p99 |
|---|--:|--:|--:|--:|
| GET /tables | 1179 | 91 ms | 145 ms | 187 ms |
| GET /service-requests | 1177 | 78 ms | 126 ms | 174 ms |
| GET /public/notices | 1178 | 89 ms | 135 ms | 187 ms |
| GET /public/menu | 1178 | 125 ms | 193 ms | 246 ms |
| GET /public/session | 1180 | 90 ms | 135 ms | 183 ms |

Defeitos encontrados e corrigidos nesta rodada:
- **Cardápio não funcionava pelo IP da rede local (HTTP)**: o botão “Adicionar” usava `crypto.randomUUID`, que
  o navegador só oferece em HTTPS/localhost. Trocado por `crypto.getRandomValues` (disponível sempre).
- **Campo do PIN sem foco ao abrir o diálogo**: o foco ia para o “×” e o Enter fechava o diálogo. O componente
  de diálogo agora foca o campo marcado com `data-autofocus`.
- **Teste instável `test_reconnect_recovers_state`** (falhava ~50% das vezes): aceitava o evento atrasado de
  criação no lugar do evento de conclusão. O filtro agora confere o status.

As seções abaixo são da execução de 23/10/2026, sobre a primeira versão (antes da simplificação).

---

Execução de 23/10/2026, ambiente de desenvolvimento (Linux, 2 vCPU), **PostgreSQL 16 e Redis 7 reais**.
Nenhum teste foi marcado como aprovado sem ser executado; nenhum teste foi removido.

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
