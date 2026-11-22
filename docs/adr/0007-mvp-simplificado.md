# ADR-0007 — MVP simplificado: o sistema avisa, a equipe resolve com um toque

**Data.** 04/11/2026.

**Contexto.** A primeira versão cresceu além do planejado: acompanhamento de pedidos por etapas (recebido,
em preparo, pronto, entregue), chamados com “quem assumiu” e prioridade, painel de caixa com comanda, forma
de pagamento e cupons, promoções com período e cupons, login com e-mail e senha e cinco abas de operação.
O papel do Andripa é **avisar os responsáveis de que uma mesa precisa de atendimento**; o restante
deixava o uso mais lento e mais difícil.

**Decisão.**
- **Página da mesa** (QR/NFC) com dois botões: **Cliente** (destaque) e **Liberar mesa** (discreto).
  Liberar pede só o **PIN** de alguém da equipe; o atendente não precisa abrir o painel.
- **Solicitações com dois momentos**: feita e resolvida, com horário de cada um. Um botão por tipo:
  *Atendido*, *Repassado à cozinha*, *Conta finalizada* (esta encerra a mesa). Sem “assumir”, prioridade,
  etapas de pedido ou forma de pagamento.
- **Login por usuário + PIN**. PIN único por estabelecimento (é ele que libera mesas).
- **Uma aba de operação (Salão)**; detalhes e histórico abrem ao tocar na mesa.
- **Promoções viram avisos** (Notificações): só informam; para saber mais, o cliente chama um atendente.
- Cliente sem aba Comanda e sem valor no “Pedir a conta”; pedidos aparecem no acompanhamento.
- Removidos: código de entrada de 4 dígitos, cupons, promoções, histórico de status de pedido, painel de
  caixa, tela de pedidos. O esquema do banco foi refeito (`0001`), pois não havia dados de produção.

**Consequências.**
- Menos telas, menos estados e menos regras: 88 testes de backend cobrindo o novo fluxo, inclusive as corridas
  (liberação simultânea, toque duplo em “Atendido”, pedido × encerramento).
- PIN de 4 dígitos é fraco para quem tem acesso administrativo: o login é limitado por usuário e IP, e a
  liberação por IP, mesa e estabelecimento; recomenda-se PIN de 6+ dígitos para administradores.
- Liberar pela página da mesa compara o PIN com o hash de cada pessoa ativa da equipe (Argon2id, fora do
  event loop). Para equipes grandes (dezenas de pessoas) vale trocar por uma busca indexada com HMAC.
- Se um dia o bar precisar de comanda/caixa, a estrutura de pedidos (itens, preços do catálogo no momento do
  pedido, total) continua gravada e pode ser reaproveitada.
