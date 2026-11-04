# Andripa — atendimento digital para bares e restaurantes

Ferramenta auxiliar para **avisar a equipe** de que uma mesa precisa de atendimento.

Cada mesa tem um QR Code (ou etiqueta NFC) que abre a **página da mesa**, com dois botões:
- **Cliente** (destaque): sem instalar nada nem criar conta, o cliente chama o atendente, vê o cardápio,
  faz pedidos, pede a conta e vê as novidades da casa.
- **Liberar mesa** (discreto): o atendente digita o **PIN** e pronto — não precisa abrir o painel.

No painel (login por **usuário + PIN**), uma única tela, o **Salão**, mostra o que está aguardando e as
mesas. Cada aviso se resolve com um toque: *Atendido*, *Repassado à cozinha* ou *Conta finalizada*.
Tocar numa mesa mostra o atendimento atual e os anteriores, com o horário de cada coisa.

- Backend: Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy 2 (async, psycopg 3) · Alembic · WebSocket
- Dados: PostgreSQL 16 (fonte da verdade + outbox) · Redis 7 (pub/sub entre instâncias, rate limiting)
- Frontend: React 19 · TypeScript (strict) · Vite · PWA (manifest + service worker) · Web Push (VAPID)
- Infra: Docker · Terraform (AWS: CloudFront, S3, ALB, ECS Fargate, RDS, ElastiCache, Secrets Manager, CloudWatch) · GitHub Actions

## Rodar localmente
Requisitos: Docker com Compose.
```bash
cp .env.example .env
docker compose up --build         # postgres, redis, api (:8000) e frontend (:5173)
docker compose exec api python -m app.cli seed-dev   # dados de DEMONSTRAÇÃO (só em development)
```
Abra http://localhost:5173 e entre com o usuário `admin`, `caixa` ou `atendente` (PINs 1111, 2222 e 3333).
Em **Mesas** você vê a URL de cada mesa — abra-a no celular ou em outra janela, toque em **Liberar mesa**
(PIN 3333) e depois em **Cliente**.

Para acessar de outros aparelhos da rede, use o IP do computador em `ANDRIPA_PUBLIC_BASE_URL` e
`ANDRIPA_ALLOWED_ORIGINS` (ex.: `http://192.168.1.5:8010`) e publique a porta em `0.0.0.0`.

Sem Docker: PostgreSQL e Redis locais, depois
```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
alembic upgrade head && python -m app.cli seed-dev && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

Para um estabelecimento real (sem dados de demonstração):
`python -m app.cli bootstrap --establishment "Nome" --tz America/Manaus --admin-name "Ana" --admin-username ana --tables 12`
(o PIN do administrador é pedido no terminal)

## Testes
```bash
# backend: precisa de PostgreSQL e Redis reais (o compose cria o banco atende_test)
cd backend && ANDRIPA_TEST_DATABASE_URL=postgresql+psycopg://atende:atende-dev@localhost:5432/atende_test pytest
# frontend
cd frontend && npm run typecheck && npm run build
# ponta a ponta: API servindo o build (ANDRIPA_FRONTEND_DIST_DIR=../frontend/dist) + seed-dev
cd frontend && npx playwright install chromium && npx playwright test
# carga
cd backend && python scripts/loadtest.py --username caixa --pin 2222
```
Resultados da última execução: [`docs/10-relatorio-testes.md`](docs/10-relatorio-testes.md)
(88 testes de backend, 4 testes e2e).

## CI/CD
Os workflows do GitHub Actions estão em `ci/github-workflows/` (`ci.yml` e `deploy.yml`). Ao criar o
repositório, mova-os para `.github/workflows/`.

## Documentação
| Documento | Conteúdo |
|---|---|
| [01 — Arquitetura](docs/01-arquitetura.md) | Fase 1 completa: requisitos, arquitetura, fluxos, modelo de dados, estratégias, plano, riscos |
| [02 — Permissões](docs/02-permissoes.md) | Matriz RBAC e regras |
| [03 — Estados](docs/03-estados.md) | Diagramas de mesa, chamado e pedido |
| [04 — API](docs/04-api.md) · [openapi.json](docs/openapi.json) | Contratos, erros, idempotência, WebSocket |
| [05 — Guia operacional](docs/05-guia-operacional.md) | Para atendentes, caixa e admin |
| [06 — AWS](docs/06-implantacao-aws.md) | Implantação, pipeline, rollback, custos |
| [07 — Backup](docs/07-backup-recuperacao.md) | Backup, restauração, retenção, LGPD |
| [08 — Checklist](docs/08-checklist-producao.md) | Publicação em produção |
| [09 — Limitações](docs/09-limitacoes.md) | O que não está pronto |
| [10 — Relatório de testes](docs/10-relatorio-testes.md) | Resultados reais |
| [ADRs](docs/adr) | Decisões de arquitetura |

## Estrutura
```
backend/   app/{api,core,db,domain,models,schemas,services,realtime} · alembic/ · tests/ · scripts/ · Dockerfile
frontend/  src/{api,realtime,components,lib,pages/{customer,staff,admin}} · public/{sw.js,manifest} · e2e/
infra/     terraform/ (AWS) · docker/ · scripts/backup_restore_test.sh
docs/      documentação, ADRs e OpenAPI
```
