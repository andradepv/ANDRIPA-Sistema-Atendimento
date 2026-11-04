# Limitações conhecidas

Nada abaixo aparece na interface como se funcionasse.

## Fora do escopo (de propósito)
O projeto trata de **chamado de garçom e gestão de mesas**. Não fazem parte dele, e foram removidos do código:
cardápio digital, pedidos pelo celular, cozinha, cupons, promoções, notificações push, valores da conta,
forma de pagamento e programa de fidelidade. A cobrança continua no caixa/PDV do estabelecimento.

- **Criação de estabelecimentos** é feita por linha de comando (`python -m app.cli bootstrap`); não há
  painel de "super administrador".
- **Métricas de atendimento** (tempo de espera por chamado, por mesa e por atendente) ainda não têm tela,
  embora os horários de criação, assunção e conclusão de cada chamado já fiquem gravados.

## Gravação de etiquetas e plantas (novo)
- **Gravar NFC pelo navegador exige Chrome para Android com NFC ligado e HTTPS** (Web NFC). iPhone e desktop
  não gravam; a mesa, o endereço e o QR Code continuam funcionando.
- **Web NFC não define senha na etiqueta (NTAG).** A proteção é o **travamento permanente** (somente leitura),
  que é irreversível e opcional. Sem travar, qualquer aplicativo NFC ainda pode regravar a etiqueta.
- **Não testado em hardware real**: o fluxo foi validado no Chromium com um leitor NFC simulado e contra o
  servidor real. Antes de gravar em lote, teste com 1–2 etiquetas NTAG213/215 num Android.
- O servidor confere que a URL lida de volta é a da mesa e que o UID não está em outra mesa, mas **não
  consegue provar** que o chip travou fisicamente; ele confia no navegador do administrador.
- A planta é uma grade de 24 × 16 células, sem rotação, formas ou tamanhos diferentes por mesa.

## Limitações técnicas
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
Ver `docs/10-relatorio-testes.md`: jornada e2e e teste de carga nesta versão, `terraform plan` na conta real,
testes em Safari/Firefox, em etiquetas NFC reais e medição de desempenho em homologação.
