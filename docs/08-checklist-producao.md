# Checklist de publicação em produção

## Infraestrutura
- [ ] Estado do Terraform em S3 criptografado com lock no DynamoDB
- [ ] `envs/production.tfvars` revisado (domínio, zona, Multi-AZ, retenção de backup, e-mail de alarmes)
- [ ] `terraform plan` revisado por uma segunda pessoa
- [ ] Assinatura do e-mail de alarmes (SNS) confirmada
- [ ] `deletion_protection` ativo no RDS e no ALB (automático em production)
- [ ] RDS e Redis sem acesso público (verificar security groups)
- [ ] Certificados ACM emitidos (CloudFront em us-east-1 e ALB)

## Segredos e configuração
- [ ] Nenhum segredo no repositório (`git grep -i -E "password|secret|token"` revisado)
- [ ] `ANDRIPA_ENVIRONMENT=production` (desliga `/docs` e o `seed-dev`)
- [ ] `ANDRIPA_COOKIE_SECURE=true`, `ANDRIPA_ALLOWED_ORIGINS=https://<domínio>`
- [ ] Chaves VAPID geradas e gravadas no Secrets Manager (se for usar push)

## Aplicação
- [ ] CI verde no commit a publicar (lint, tipos, bandit, pip-audit, npm audit, testes, e2e)
- [ ] Homologação publicada com a mesma imagem e smoke test ok
- [ ] Migração testada em homologação; snapshot manual do RDS se houver mudança de esquema
- [ ] `python -m app.cli bootstrap` executado; senha do admin trocada no primeiro acesso
- [ ] Equipe cadastrada com contas individuais e PIN pessoal

## Validação funcional em homologação (cenários de aceitação)
- [ ] A — abrir mesa e acessar pelo QR e pela etiqueta NFC em um Android e um iPhone
- [ ] B — mesa livre mostra “não disponível”
- [ ] C — chamar atendente aparece no painel em < 1 s
- [ ] D — pedido com adicional chega correto à tela Pedidos
- [ ] E — pedir a conta mantém a mesa ocupada
- [ ] F — fechar conta: celular do cliente perde o acesso
- [ ] G — dois funcionários abrindo a mesma mesa: só uma abertura
- [ ] H — derrubar o Wi-Fi do tablet e voltar: painel recupera tudo
- [ ] I — atendente não acessa funções administrativas
- [ ] J — ambiente subiu só com a documentação
- [ ] Medição de desempenho em homologação (`scripts/loadtest.py`) registrada

## Operação
- [ ] Teste de restauração do backup executado e registrado
- [ ] Painel CloudWatch e alarmes verificados (forçar um 5xx de teste)
- [ ] Responsável de plantão e procedimento de rollback conhecidos
- [ ] QR Codes impressos e etiquetas NFC gravadas com a URL de **produção**
- [ ] Equipe treinada com `docs/05-guia-operacional.md`
