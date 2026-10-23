# Plano de backup e recuperação

## O que é crítico
Somente o **PostgreSQL** guarda estado. Redis é descartável (pub/sub e contadores de rate limit); o
frontend é reconstruído do repositório; segredos estão no Secrets Manager.

## Backups
| Tipo | Como | Retenção |
|---|---|---|
| Snapshots automáticos + PITR do RDS | `backup_retention_period` (7 dias homologação, 14 produção) | conforme variável |
| Snapshot manual antes de migração arriscada | `aws rds create-db-snapshot --db-instance-identifier andripa-production --db-snapshot-identifier pre-<versao>` | até remoção manual |
| Snapshot final ao destruir produção | `final_snapshot_identifier` + `deletion_protection` | permanente |
| Dump lógico mensal (opcional, cópia fora da conta) | `pg_dump -Fc` a partir de uma instância restaurada | 12 meses |

Objetivos: **RPO ≤ 5 min** (PITR) · **RTO ≤ 1 h** (restaurar instância + trocar `DATABASE_URL`).

## Restauração (procedimento)
1. Restaure para um ponto no tempo em uma **nova** instância:
   `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier andripa-production --target-db-instance-identifier andripa-production-restore --restore-time 2026-10-23T03:00:00Z --db-subnet-group-name andripa-production --vpc-security-group-ids <sg-db>`
2. Valide: conecte por uma tarefa ECS avulsa e rode as contagens do script `infra/scripts/backup_restore_test.sh`.
3. Atualize `DATABASE_URL` no Secrets Manager para o novo endpoint e force novo deploy do serviço ECS
   (`aws ecs update-service --force-new-deployment`).
4. Os painéis reconectam e ressincronizam sozinhos. Clientes de mesas abertas continuam com os tokens
   existentes (se o ponto restaurado for anterior à abertura, a mesa precisará ser reaberta).
5. Depois de estabilizar, remova ou renomeie a instância antiga.

## Teste de restauração
`infra/scripts/backup_restore_test.sh` faz dump → restauração em banco novo → comparação de contagens →
verificação da versão do esquema. **Executado com sucesso** em desenvolvimento (ver relatório de testes).
Em produção, repita **trimestralmente** contra uma instância restaurada de snapshot e registre o resultado.

## Retenção de dados operacionais (recomendação)
Rodar diariamente (tarefa agendada no ECS/EventBridge — não incluída nesta entrega):
```sql
DELETE FROM outbox_events     WHERE published_at < now() - interval '7 days';
DELETE FROM idempotency_keys  WHERE created_at   < now() - interval '1 day';
DELETE FROM customer_tokens   WHERE revoked_at   < now() - interval '30 days';
DELETE FROM staff_sessions    WHERE coalesce(revoked_at, expires_at) < now() - interval '30 days';
DELETE FROM push_subscriptions WHERE revoked_at  < now() - interval '30 days';
```
Pedidos, sessões e auditoria são histórico contábil e operacional: manter conforme a política fiscal do
estabelecimento.

## LGPD
O sistema não pede nome, telefone ou e-mail do cliente. Dados pessoais armazenados: contas da equipe,
identificação opcional da mesa (texto livre — oriente a equipe a usar só o primeiro nome) e inscrições
push (endpoint do navegador, com consentimento explícito e cancelamento a qualquer momento).
