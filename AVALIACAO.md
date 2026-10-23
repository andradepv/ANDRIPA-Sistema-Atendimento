# Avaliação independente do sistema Andripa

Data: 23/10/2026 · Ambiente: Windows 11 + Docker (PostgreSQL 16, Redis 7, Python 3.13, Node 24, Chromium)

## 1. O que é o sistema

**Andripa** é uma plataforma de **atendimento digital para bares e restaurantes**. Cada mesa tem um
QR Code (ou etiqueta NFC). O cliente aponta o celular e, **sem instalar app nem criar conta**:

- chama o atendente com um toque;
- vê o cardápio (com adicionais, promoções e cupons) e faz pedidos;
- acompanha o andamento dos pedidos em tempo real;
- vê a comanda e pede a conta.

A equipe usa um painel web com perfis distintos:

| Perfil | O que faz |
|---|---|
| **Atendente** | Abre mesas (confirmando com PIN), assume e conclui chamados, acompanha pedidos |
| **Caixa** | Abre a comanda, registra a forma de pagamento e encerra a mesa (o celular do cliente perde o acesso na hora) |
| **Administrador** | Cardápio, mesas e QR Codes, equipe, promoções, notificações push, auditoria e configurações |

O que **não** faz (declarado em `docs/09-limitacoes.md`): pagamento online, fidelidade, upload de
imagens, impressão térmica na cozinha, painel de "super admin" (estabelecimentos são criados por CLI).

### Arquitetura

- **Backend**: FastAPI + SQLAlchemy 2 assíncrono + PostgreSQL (fonte da verdade) + Redis (pub/sub entre
  instâncias e rate limiting). Eventos em tempo real via **WebSocket**, com padrão **outbox** para não
  perder eventos se o Redis cair.
- **Frontend**: React 19 + TypeScript estrito + Vite, como **PWA** (service worker, manifest, Web Push VAPID).
- **Infra**: Docker, Terraform para AWS (CloudFront, S3, ALB, ECS Fargate, RDS, ElastiCache), GitHub Actions.
- **Tamanho**: ~3.750 linhas de Python na aplicação, ~3.000 de TSX, 87 testes de backend, 3 jornadas e2e,
  10 documentos + 6 ADRs.

## 2. Testes executados nesta avaliação

| Verificação | Resultado |
|---|---|
| `pytest` (87 testes, Postgres e Redis reais) | **86 passaram, 1 falhou** (intermitente, ver §3.1) |
| Teste intermitente repetido 10× | 5 verdes, 5 vermelhos |
| `mypy app` | 0 problemas em 45 arquivos |
| `ruff check` | 10 avisos de estilo (UP042/UP046) — ver §3.2 |
| `bandit` | 0 alto, 0 médio, 13 baixos (uso de `assert`, etc.) |
| `pip-audit` / `npm audit` | **0 vulnerabilidades conhecidas** |
| `tsc --noEmit` (strict) | 0 erros |
| `vite build` | OK — JS 302 kB (91 kB gzip), CSS 19 kB |
| Playwright e2e (Chromium) | **3/3 passaram** (jornada completa, navegador sem push, mesa livre bloqueada) |
| Teste de carga (20 clientes, 30 s) | **211 req/s, 0 erros**, p95 entre 86 e 130 ms |
| Inspeção manual no navegador | Login, painel de salão, cadastro de mesas/QR e tela do cliente no celular funcionando |
| Tentativa de burlar o limite de login forjando `X-Forwarded-For` | **Bloqueado** (limite por e-mail segura) |

Carga detalhada:

| Endpoint | Req. | Erros | p50 | p95 | p99 |
|---|--:|--:|--:|--:|--:|
| GET /tables | 1266 | 0 | 93 ms | 106 ms | 162 ms |
| GET /service-requests | 1266 | 0 | 72 ms | 86 ms | 96 ms |
| GET /orders | 1266 | 0 | 76 ms | 92 ms | 141 ms |
| GET /public/menu | 1270 | 0 | 111 ms | 127 ms | 182 ms |
| GET /public/session | 1264 | 0 | 113 ms | 130 ms | 180 ms |

Os números ficaram **melhores** que os do relatório do projeto (p95 < 260 ms) porque aqui foi usado o
driver psycopg binário.

## 3. Problemas encontrados

### 3.1 Teste instável — `test_reconnect_recovers_state` (prioridade média)
`backend/tests/test_realtime.py:253`. O teste espera o evento `request.updated` do chamado assumido, mas o
filtro aceita qualquer `request.updated` daquele chamado. Às vezes o evento **de criação** (status
`PENDENTE`), entregue com atraso pelo outbox, chega primeiro ao socket reconectado e o teste falha.
**Não é defeito do produto**: o frontend descarta versões antigas (`upsertVersioned`). Correção: filtrar
também por `status == "ASSUMIDA"` no predicado. Isso contradiz o relatório interno ("15/15 verdes") e
derrubaria o CI em ~50% das execuções.

### 3.2 Dependências sem versão fixa (prioridade média)
`requirements*.txt` usam `>=`. A instalação de hoje trouxe ruff 0.17, que acusa 10 avisos novos e faria
o `ruff check` do CI falhar sem nenhuma mudança no código. O próprio arquivo pede um `requirements.lock`
via `pip-compile`, que não existe. O mesmo vale para o `package-lock.json` do frontend (não versionado).

### 3.3 `--forwarded-allow-ips "*"` no Dockerfile (prioridade baixa)
Com `*`, o uvicorn usa o **primeiro** IP do `X-Forwarded-For`, que o cliente controla. Os limites
apenas por IP (`pub:ip`, `join:ip`, `cust:ip`, `coupon:ip`, `push:ip`) podem ser contornados. O risco é
contido porque quase todos têm um segundo limite por sessão/token/e-mail (confirmado no teste de login).
Recomendação: confiar só na faixa da VPC do ALB, ou ler o IP do cabeçalho `CloudFront-Viewer-Address`.

### 3.4 Itens menores
- Código de entrada da mesa (quando habilitado) tem 4 dígitos e limite de 30 tentativas/10 min por
  sessão: em 12 h de mesa aberta, ~20% de chance de acerto por força bruta para quem tem a URL da mesa.
  Aceitável para o cenário, mas pode ser reforçado (bloqueio após N erros + alerta ao atendente).
- Workflows do CI estão em `ci/github-workflows/` e o projeto não é um repositório git: o CI ainda não roda.
- `httpx` com `TestClient` gera aviso de descontinuação no Starlette atual.
- Sem rotina automática de expurgo de dados (declarado nas limitações).

## 4. Pontos fortes

- **Segurança acima da média**: Argon2id, tokens opacos guardados só como hash SHA-256, cookies
  `HttpOnly`/`SameSite=Strict`, CSRF com comparação em tempo constante, CORS e origem do WebSocket
  restritos, limite de corpo, cabeçalhos de segurança, códigos de mesa com 128 bits, isolamento entre
  estabelecimentos testado, trilha de auditoria.
- **Concorrência tratada de verdade**: bloqueios `FOR UPDATE`, idempotência, testes com aberturas e
  chamados simultâneos, corrida pedido × encerramento.
- **Tempo real robusto**: outbox + Redis, funcionamento degradado testado com Redis fora, ressincronização
  por REST.
- **Documentação honesta e completa**: arquitetura, RBAC, estados, API/OpenAPI, guia operacional,
  implantação AWS, backup, checklist, limitações e ADRs.
- **UX simples e clara** no celular do cliente.

## 5. Veredito

**Sistema bem construído e praticamente pronto para homologação.** Funciona de ponta a ponta, é rápido,
sem vulnerabilidades conhecidas nas dependências e com engenharia de segurança e concorrência cuidadosa.

Antes de produção: corrigir o teste instável (§3.1), fixar versões das dependências (§3.2), ajustar a
confiança no `X-Forwarded-For` (§3.3), criar o repositório git e ativar o CI, e executar o que o próprio
projeto lista como pendente (`terraform plan` na AWS, push em aparelhos reais, Safari/Firefox).

**Nota geral: 8,5/10.**
