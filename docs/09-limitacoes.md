# Limitações conhecidas

Nada abaixo aparece na interface como se funcionasse.

## Fora do escopo desta entrega
- **Pagamento online**: não há cobrança. O caixa registra a forma de pagamento usada na maquininha/Pix.
- **Programa de fidelidade** (`LoyaltyRecords`): não implementado e sem botões na interface. Estrutura
  sugerida para a próxima etapa: tabela `loyalty_accounts` (identificador do cliente com consentimento,
  ex.: telefone com hash) e `loyalty_events` (pontos por sessão encerrada), creditados no fechamento.
- **Upload de imagens** do cardápio: o admin informa uma URL `https://`. Upload para S3 com URL pré-assinada
  fica para a próxima etapa.
- **Itens lançados pelo atendente**: pedidos são feitos pelo celular do cliente. O caixa vê apenas o que
  foi registrado no sistema; itens anotados à parte precisam ser lançados no PDV atual do estabelecimento.
- **Impressão de comanda na cozinha** (impressora térmica): não implementada; a cozinha usa a tela Pedidos.
- **Criação de estabelecimentos** é feita por linha de comando (`python -m app.cli bootstrap`); não há
  painel de "super administrador".

## Limitações técnicas
- **Push no iPhone** só funciona com o site adicionado à tela de início (iOS 16.4+); a tela informa isso.
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
