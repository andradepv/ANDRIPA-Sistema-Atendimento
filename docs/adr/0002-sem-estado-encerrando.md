# ADR-0002 — Sem estado intermediário ENCERRANDO

**Contexto.** O requisito sugere ENCERRANDO "se necessário para operações concorrentes".
**Decisão.** O encerramento roda em uma única transação com `SELECT … FOR UPDATE` na mesa e na sessão (sempre nessa ordem, evitando deadlock). Pedidos e chamados do cliente também bloqueiam a mesa antes de gravar.
**Consequências.** Não existe estado intermediário observável nem mesa "presa" em ENCERRANDO após uma falha. A corrida pedido × encerramento é testada (`test_order_vs_close_race`). Se no futuro o encerramento depender de um serviço externo lento (ex.: pagamento online), um estado intermediário passa a fazer sentido.
