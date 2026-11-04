# Andripa — atendimento digital para bares e restaurantes

Sistema de **chamado de garçom e gestão de mesas**. O cliente lê o QR Code (ou encosta o celular na etiqueta
NFC) da mesa e, sem instalar nada nem criar conta, chama o atendente ou pede a conta e acompanha o estado do
chamado em tempo real. A equipe vê todas as mesas e chamados em painéis para **atendente**, **caixa** e
**administrador**: abrir e encerrar mesas, assumir chamados (um único atendente por chamado), priorizar, e
administrar mesas, QR Codes, etiquetas NFC e a planta do salão.

Fora do escopo de propósito: cardápio, pedidos, cupons, promoções, notificações push e cobrança. A conta
continua sendo fechada no caixa/PDV do estabelecimento.

- Backend: Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy 2 (async, psycopg 3) · Alembic · WebSocket
- Dados: PostgreSQL 16 (fonte da verdade + outbox) · Redis 7 (pub/sub entre instâncias, rate limiting)
- Frontend: React 19 · TypeScript (strict) · Vite · PWA (manifest + service worker)
- Infra: Docker · Terraform (AWS: CloudFront, S3, ALB, ECS Fargate, RDS, ElastiCache, Secrets Manager, CloudWatch) · GitHub Actions

## Rodar localmente
Requisitos: Docker com Compose.
```bash
cp .env.example .env              # ajuste ANDRIPA_DEV_PASSWORD
docker compose up --build         # postgres, redis, api (:8000) e frontend (:5173)
docker compose exec api python -m app.cli seed-dev   # dados de DEMONSTRAÇÃO (só em development)
```
Abra http://localhost:5173 e entre com `admin@demo.local`, `caixa@demo.local` ou `atendente@demo.local`
(senha = `ANDRIPA_DEV_PASSWORD`; PINs 1111, 2222 e 3333). Em **Mesas** você vê a URL de cada mesa —
abra-a no celular ou em outra janela para fazer o papel do cliente.

Sem Docker: PostgreSQL e Redis locais, depois
```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
alembic upgrade head && python -m app.cli seed-dev && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

Para um estabelecimento real (sem dados de demonstração):
`python -m app.cli bootstrap --establishment "Nome" --tz America/Manaus --admin-name "Ana" --admin-email ana@exemplo.com --tables 12`

## Testes
```bash
# backend: precisa de PostgreSQL e Redis reais (o compose cria o banco atende_test)
cd backend && ANDRIPA_TEST_DATABASE_URL=postgresql+psycopg://atende:atende-dev@localhost:5432/atende_test pytest
# frontend
cd frontend && npm run typecheck && npm run build
# ponta a ponta: API servindo o build (ANDRIPA_FRONTEND_DIST_DIR=../frontend/dist) + seed-dev
cd frontend && npx playwright install chromium && E2E_PASSWORD=<senha-dev> npx playwright test
# carga
cd backend && python scripts/loadtest.py --email caixa@demo.local --password <senha-dev>
```
Resultados da última execução: [`docs/10-relatorio-testes.md`](docs/10-relatorio-testes.md)
(testes de backend e verificações estáticas desta versão).

## CI/CD
Os workflows do GitHub Actions estão em `ci/github-workflows/` (`ci.yml` e `deploy.yml`). Ao criar o
repositório, mova-os para `.github/workflows/`.

## Documentação
| Documento | Conteúdo |
|---|---|
| [01 — Arquitetura](docs/01-arquitetura.md) | Requisitos, arquitetura, fluxos, modelo de dados, estratégias de concorrência |
| [02 — Permissões](docs/02-permissoes.md) | Matriz RBAC e regras |
| [03 — Estados](docs/03-estados.md) | Diagramas de mesa, sessão, chamado e etiqueta |
| [04 — API](docs/04-api.md) · [openapi.json](docs/openapi.json) | Contratos, erros, idempotência, WebSocket |
| [05 — Guia operacional](docs/05-guia-operacional.md) | Para atendentes, caixa e admin |
| [06 — AWS](docs/06-implantacao-aws.md) | Implantação, pipeline, rollback, custos |
| [07 — Backup](docs/07-backup-recuperacao.md) | Backup, restauração, retenção, LGPD |
| [08 — Checklist](docs/08-checklist-producao.md) | Publicação em produção |
| [09 — Limitações](docs/09-limitacoes.md) | O que não está pronto |
| [10 — Relatório de testes](docs/10-relatorio-testes.md) | Resultados reais |
| [11 — Etiquetas NFC e planta do salão](docs/11-etiquetas-e-planta.md) | Criar mesa + gravar etiqueta, status ao vivo, templates de planta |
| [ADRs](docs/adr) | Decisões de arquitetura |

## Estrutura
```
backend/   app/{api,core,db,domain,models,schemas,services,realtime} · alembic/ · tests/ · scripts/ · Dockerfile
frontend/  src/{api,realtime,components,lib,pages/{customer,staff,admin}} · public/{sw.js,manifest} · e2e/
infra/     terraform/ (AWS) · docker/ · scripts/backup_restore_test.sh
docs/      documentação, ADRs e OpenAPI
```
