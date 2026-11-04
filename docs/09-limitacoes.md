# Limitações conhecidas

Nada abaixo aparece na interface como se funcionasse.

## Fora do escopo desta entrega
- **Pagamento online e comanda**: não há cobrança, forma de pagamento nem conta detalhada. O caixa recebe
  como de costume e toca em “Conta finalizada”.
- **Programa de fidelidade** (`LoyaltyRecords`): não implementado e sem botões na interface. Estrutura
  sugerida para a próxima etapa: tabela `loyalty_accounts` (identificador do cliente com consentimento,
  ex.: telefone com hash) e `loyalty_events` (pontos por sessão encerrada), creditados no fechamento.
- **Upload de imagens** do cardápio: o admin informa uma URL `https://`. Upload para S3 com URL pré-assinada
  fica para a próxima etapa.
- **Acompanhamento de preparo**: o sistema só avisa que há um pedido; a equipe o repassa à cozinha e toca em
  “Repassado à cozinha”. Não há etapas de preparo nem tela de cozinha.
- **Promoções e cupons**: substituídos por avisos simples (aba Novidades); o cliente chama um atendente para
  saber mais. Não há desconto calculado pelo sistema.
- **Criação de estabelecimentos** é feita por linha de comando (`python -m app.cli bootstrap`); não há
  painel de "super administrador".

## Limitações técnicas
- **Push no iPhone** só funciona com o site adicionado à tela de início (iOS 16.4+); a tela informa isso.
- **PIN como credencial**: PIN de 4 dígitos é fraco para administradores (use 6+). As tentativas são
  limitadas e auditadas. Liberar mesa compara o PIN com cada pessoa ativa (Argon2id): rápido para equipes
  pequenas; para dezenas de pessoas, trocar por busca indexada (HMAC).
- **Rate limiting** usa janela fixa; durante indisponibilidade do Redis cada instância limita sozinha
  (o limite efetivo se multiplica pelo número de instâncias nesse período).
- **Eventos com mais de 10 minutos** pendentes no outbox (Redis fora por muito tempo) não são reenviados;
  os painéis se ressincronizam pelo REST a cada 30 s e em toda reconexão.
- **Sessão de funcionário** expira após 2 h sem uso ou 12 h no total; o painel volta ao login.
- **Um NAT Gateway** na infraestrutura padrão (economia). Para alta disponibilidade, um por zona.
- **Retenção de dados**: não há rotina automática de expurgo. Recomenda-se apagar `outbox_events` publicados
  há mais de 7 dias, `idempotency_keys` com mais de 24 h e `customer_tokens` revogados há mais de 30 dias
  (ver `docs/07-backup-recuperacao.md`, seção Retenção).

## Verificações pendentes antes de produção
Ver `docs/10-relatorio-testes.md` §6: build Vite e Docker no CI, `terraform plan` na conta real,
push em aparelhos reais, testes em Safari/Firefox e medição de desempenho em homologação.
