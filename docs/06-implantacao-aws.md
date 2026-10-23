# Implantação na AWS

## Arquitetura implantada (`infra/terraform`)
| Recurso | Uso |
|---|---|
| VPC 2 AZs, sub-redes públicas (ALB, NAT) e privadas (ECS, RDS, Redis) | Banco e Redis sem acesso à internet |
| CloudFront + ACM (us-east-1) | HTTPS do domínio; `/*` → S3, `/api/*` → ALB (sem cache, WebSocket) |
| S3 privado (OAC, versionado, criptografado) | Build do frontend |
| ALB HTTPS (ACM) com regra de cabeçalho secreto | Só aceita tráfego vindo do CloudFront; idle 300 s para WebSocket |
| ECS Fargate ARM64, 2+ tarefas, autoscaling por CPU, circuit breaker com rollback | API |
| Tarefa ECS avulsa `migrate` | `alembic upgrade head` antes de cada deploy |
| RDS PostgreSQL 16 (criptografado, SSL obrigatório, backups, Performance Insights) | Fonte da verdade |
| ElastiCache Redis 7 (TLS, criptografia em repouso) | Pub/Sub e rate limiting |
| Secrets Manager | `DATABASE_URL`, `REDIS_URL`, chaves VAPID |
| CloudWatch Logs (JSON), filtros de métrica e alarmes → SNS | Erros, Redis degradado, 5xx, p95, alvos não saudáveis, CPU e disco do RDS |
| ECR (tags imutáveis, scan) | Imagens da API (últimas 30 mantidas para rollback) |

## Pré-requisitos (uma vez por conta)
1. Domínio com zona no Route 53.
2. Bucket S3 + tabela DynamoDB para o estado do Terraform (criptografado) — preencha
   `infra/terraform/envs/<env>.backend.hcl`.
3. Role IAM para o GitHub Actions via OIDC (`AWS_DEPLOY_ROLE_ARN`) e variável `ECR_REPOSITORY_URL` nos
   *environments* `staging` e `production` do GitHub. Exija aprovação manual em `production`.
4. Preencha `envs/<env>.tfvars` (domínio, zona, tamanhos).

## Primeira publicação
```bash
cd infra/terraform
terraform init -backend-config=envs/staging.backend.hcl
# 1ª vez: cria ECR antes de existir imagem
terraform apply -var-file=envs/staging.tfvars -var api_image_tag=bootstrap -target=aws_ecr_repository.api
# publique a imagem (ou deixe o CI fazer)
docker buildx build --platform linux/arm64 -t <ecr>:<sha> backend --push
terraform apply -var-file=envs/staging.tfvars -var api_image_tag=<sha>
# migração (o CI faz isso automaticamente; ver .github/workflows/deploy.yml)
aws ecs run-task --cluster andripa-staging --task-definition andripa-staging-migrate ...
# chaves de push (opcional)
docker run --rm <ecr>:<sha> python -m app.cli gen-vapid
aws secretsmanager put-secret-value --secret-id andripa-staging/app --secret-string '{...com as chaves...}'
# estabelecimento e primeiro administrador (tarefa avulsa com o comando abaixo)
python -m app.cli bootstrap --establishment "Nome do Bar" --tz America/Manaus --admin-name "..." --admin-email ...
```
Depois: `npm run build` no frontend, `aws s3 sync` e invalidação do CloudFront (feito pelo CI).

## Pipeline (`.github/workflows`)
PR → lint, tipos, bandit, pip-audit, testes com PostgreSQL/Redis, migração ida e volta, build e auditoria
do frontend, e2e Playwright. `main` → imagem ARM64 no ECR (SBOM) → **homologação** (terraform → migração →
serviço estável → frontend → smoke test). Produção: `workflow_dispatch` com `deploy_production=true`, após
homologação, com aprovação manual do environment.

## Rollback
- **API**: o circuit breaker do ECS reverte sozinho se a nova versão não fica saudável. Manual:
  `terraform apply -var api_image_tag=<sha anterior>`.
- **Frontend**: bucket versionado; os assets têm hash e não são apagados no deploy, então basta
  republicar o `index.html` anterior e invalidar o CloudFront.
- **Banco**: migrações são aditivas por padrão. Mudança destrutiva só com migração em duas etapas
  (expandir → migrar dados → contrair em deploy posterior) e snapshot manual antes
  (`aws rds create-db-snapshot`). Ver `07-backup-recuperacao.md`.

## Custo estimado (sa-east-1, sob demanda, por mês — confirme na AWS Pricing Calculator)
| Item | Homologação | Produção |
|---|--:|--:|
| NAT Gateway (1) + tráfego | ~US$ 45 | ~US$ 50 |
| ALB | ~US$ 25 | ~US$ 30 |
| ECS Fargate ARM (0,5 vCPU / 1 GB) | 1 tarefa ~US$ 20 | 2 tarefas ~US$ 40 |
| RDS PostgreSQL | t4g.small ~US$ 50 | t4g.medium Multi-AZ ~US$ 200 |
| ElastiCache Redis | t4g.micro ×1 ~US$ 20 | t4g.micro ×2 ~US$ 40 |
| CloudFront + S3 | < US$ 5 | ~US$ 10 |
| CloudWatch, Secrets Manager, ECR | ~US$ 10 | ~US$ 20 |
| **Total aproximado** | **~US$ 175** | **~US$ 390** |

Valores de referência de ordem de grandeza, não cotação. Para um único bar pequeno, uma alternativa
mais barata documentada é 1 tarefa Fargate e RDS sem Multi-AZ (~US$ 150–180/mês).
