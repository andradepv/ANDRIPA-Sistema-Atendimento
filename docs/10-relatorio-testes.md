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

## 1. Backend — `pytest` (87 testes, 0 falhas, 52,7 s)

| Arquivo | Testes | Falhas | O que cobre |
|---|--:|--:|---|
| `test_auth.py` | 9 | 0 | Login/logout, flags do cookie, senha errada, usuário inativo, CSRF, rate limit de login, revogação ao trocar papel, último admin, troca de PIN |
| `test_permissions.py` | 21 | 0 | Matriz RBAC (8 funções admin × atendente/caixa), escalonamento de privilégio, caixa × atendente, acesso sem autenticação, **isolamento entre estabelecimentos** |
| `test_tables.py` | 10 | 0 | Abertura (A), mesa ocupada → 409, confirmação individual (PIN/senha), idempotência, **9 aberturas simultâneas → 1 sessão** (G), QR SVG, rotação de código, encerramento e revogação (E/F), token antigo × sessão nova |
| `test_customer.py` | 10 | 0 | Mesa livre bloqueada (B), códigos adivinhados, nenhum ID interno exposto, chamar atendente e deduplicação (C), **12 chamados concorrentes → 1 registro**, Idempotency-Key, cancelamento, cliente não toca outra mesa, código de entrada + força bruta, rate limit |
| `test_orders.py` | 10 | 0 | Cardápio e pedido (D), manipulação de preço/quantidade, preço do catálogo no momento da confirmação, adicionais inválidos, indisponível, transições e histórico, bloqueio por pedidos pendentes, total da conta, **6 reenvios simultâneos → 1 pedido**, **corrida pedido × encerramento** |
| `test_requests.py` | 5 | 0 | **5 funcionários assumindo o mesmo chamado → 1 responsável**, só o responsável/supervisor conclui, prioridade e ordenação, conta concluída só pelo caixa, persistência após recarregar |
| `test_realtime.py` | 6 | 0 | **Duas instâncias reais (uvicorn)**: entrega entre instâncias via Redis, sem duplicatas, WebSocket do cliente recebe pedido e é encerrado com 4001 no fechamento, autorização do WebSocket (sem cookie, cookie inválido, origem estranha), logout derruba o painel, **reconexão recupera estado** (H) |
| `test_realtime_degraded.py` | 1 | 0 | **Redis inacessível**: health "degraded", chamado persistido e entregue nas duas instâncias via outbox, rate limit local ativo |
| `test_push_promotions.py` | 6 | 0 | **Web Push conferido byte a byte com o vetor da RFC 8291**, assinatura VAPID válida, push desligado por padrão, consentimento obrigatório, envio com descarte de inscrição expirada (410), promoções só no período, cupons (validação, expiração, limite de uso atômico) |
| `test_security.py` | 9 | 0 | Limite de corpo (413), UUID/JSON inválidos, SQL injection tratada como dado, cabeçalhos de segurança, CORS restrito, tokens forjados, tokens e senhas nunca em texto puro (Argon2id), trilha de auditoria, health |

Estabilidade dos testes de concorrência: o conjunto (abertura simultânea, corrida pedido × fechamento,
reenvio idempotente, disputa de chamado, chamados concorrentes) foi executado **15 vezes seguidas: 15/15 verdes**.

> Um defeito real foi encontrado por esses testes durante o desenvolvimento: a leitura com `FOR UPDATE`
> devolvia o objeto já carregado na sessão do ORM sem atualizá-lo, permitindo que um pedido entrasse numa
> mesa que acabara de ser encerrada. Corrigido com `populate_existing` em todas as leituras com bloqueio;
> `test_order_vs_close_race` protege contra regressão.

## 2. Ponta a ponta no navegador — Playwright/Chromium (3 testes, 0 falhas, 11,6 s)

| Teste | Cenários |
|---|---|
| Jornada completa: atendente abre mesa (PIN errado recusado, PIN certo aceito) no desktop → cliente em celular (390×844) abre a URL da mesa → chama atendente → painel recebe em tempo real → atendente assume e o celular mostra "a caminho" → cliente monta pedido com adicional → cozinha avança até "Entregue" e o celular acompanha → atendente não vê/acessa funções admin (403) → cliente pede a conta → caixa abre a comanda e fecha → **celular cai para "Atendimento encerrado" na hora** → recarregar não devolve acesso → mesa volta a Livre | A, C, D, E, F, I |
| Navegador **sem Push API** (simulado): informa a limitação e o atendimento continua funcionando | §12 |
| Mesa livre e código inexistente | B |

O QR Code gerado pelo sistema foi decodificado a partir de uma captura de tela (OpenCV) e retornou
exatamente a URL pública da mesa.

## 3. Desempenho (medido, não estimado)

**Tempo real entre instâncias** (POST na instância A → evento no WebSocket da instância B, 30 amostras):
p50 **76,9 ms**, p95 **118,7 ms**, máx. 119,5 ms. Meta de referência: p95 < 1 s. ✔

**Leituras comuns sob carga** (`backend/scripts/loadtest.py`, 20 clientes simultâneos por 30 s, 1 processo
uvicorn, PostgreSQL e Redis locais, 119,5 req/s, 0 erros):

| Endpoint | Requisições | p50 | p95 | p99 |
|---|--:|--:|--:|--:|
| GET /tables | 717 | 156,0 ms | 208,7 ms | 274,2 ms |
| GET /service-requests | 715 | 118,2 ms | 169,8 ms | 231,2 ms |
| GET /orders | 718 | 119,7 ms | 165,0 ms | 229,2 ms |
| GET /public/menu | 719 | 195,0 ms | 256,9 ms | 326,2 ms |
| GET /public/session | 716 | 191,4 ms | 256,4 ms | 311,8 ms |

Meta de referência: p95 < 500 ms. ✔ Observação: o ambiente de teste usou o driver psycopg em modo
Python puro e SQLAlchemy sem extensões C; a imagem de produção usa `psycopg[binary]`, que é mais rápido.
Repita a medição em homologação na AWS antes de fixar metas definitivas.

## 4. Backup e restauração

`infra/scripts/backup_restore_test.sh` executado contra o banco de desenvolvimento: `pg_dump` → `pg_restore`
em banco novo → contagem idêntica em 8 tabelas e versão de esquema `0001`. **OK**.

## 5. Qualidade estática

| Verificação | Resultado |
|---|---|
| `ruff check app tests` (inclui regras de segurança `S`, `ASYNC`, `B`) | 0 problemas |
| `mypy app` (check_untyped_defs) | 0 problemas em 45 arquivos |
| `tsc --noEmit` (strict, noUncheckedIndexedAccess) | 0 erros |
| `alembic upgrade → downgrade base → upgrade` + `alembic check` | sem divergência entre modelos e migração |
| `tofu validate` (OpenTofu 1.8.5, provider AWS 5.80) na infraestrutura Terraform | configuração válida |

## 6. O que NÃO foi executado neste ambiente (e por quê)

O ambiente de desenvolvimento não tinha acesso aos registros pip/npm nem à AWS. Por isso:

- **`vite build`** não foi executado; o frontend foi verificado com `tsc` estrito e empacotado com
  esbuild para os testes no navegador. O build oficial roda no CI (`npm run build`).
- **`docker build`**, **`bandit`** e **`pip-audit`/`npm audit`** rodam no CI; não aqui.
- **`terraform plan/apply`** não foi executado (sem conta AWS); apenas `validate`.
- **Entrega de push a um navegador real** (via FCM/Mozilla/Apple) não foi testada; a criptografia e o
  VAPID foram validados contra a RFC e o envio contra um servidor de push simulado.
- Testes em Firefox/Safari reais e em aparelhos físicos (NFC) não foram feitos; NFC é só uma etiqueta
  passiva com a mesma URL do QR Code, então o teste do QR cobre o fluxo do sistema.
