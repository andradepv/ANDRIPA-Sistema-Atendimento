# Máquinas de estado

Implementadas em `backend/app/domain/states.py`. Transições fora destas tabelas retornam
`409 invalid_transition`. Diagramas em Mermaid (renderizam no GitHub).

## Mesa
```mermaid
stateDiagram-v2
    [*] --> LIVRE
    LIVRE --> OCUPADA: abrir (atendente+, PIN/senha)\ncria sessão OPEN
    OCUPADA --> ENCERRAMENTO_SOLICITADO: pedir conta (cliente ou equipe)
    ENCERRAMENTO_SOLICITADO --> OCUPADA: cancelar pedido de conta (caixa/admin)
    OCUPADA --> LIVRE: encerrar (caixa/admin)
    ENCERRAMENTO_SOLICITADO --> LIVRE: encerrar (caixa/admin)
```
Encerrar exige: sessão aberta, versão esperada (se enviada) igual à atual e **nenhum pedido pendente**
(`RECEBIDO`, `EM_PREPARO`, `PRONTO`) — ou a política explícita `cancel_pending` com motivo. No mesmo COMMIT:
pedidos pendentes cancelados (se for o caso), cupom resgatado, totais gravados, tokens do cliente revogados,
chamados ativos finalizados, mesa `LIVRE`, eventos no outbox.

## Sessão da mesa
`OPEN → CLOSED`. No máximo uma `OPEN` por mesa (índice único parcial `uq_open_session_per_table`).

## Chamado (service request)
```mermaid
stateDiagram-v2
    [*] --> PENDENTE
    PENDENTE --> ASSUMIDA: assumir (exclusivo, UPDATE condicional)
    PENDENTE --> EM_ATENDIMENTO: pedido entrou em preparo
    PENDENTE --> CONCLUIDA
    PENDENTE --> CANCELADA: cliente cancela / encerramento
    ASSUMIDA --> EM_ATENDIMENTO: iniciar
    ASSUMIDA --> CONCLUIDA
    ASSUMIDA --> CANCELADA
    EM_ATENDIMENTO --> CONCLUIDA
    EM_ATENDIMENTO --> CANCELADA
```
- Tipos: `CHAMAR_ATENDENTE`, `NOVO_PEDIDO` (um por pedido, acompanha o pedido), `PEDIR_CONTA`.
- Um chamado **ativo** por tipo e sessão (exceto `NOVO_PEDIDO`): repetir o toque devolve o mesmo chamado.
  Depois de concluído, um novo chamado legítimo é aceito.
- `PEDIR_CONTA` é concluído pelo caixa ao encerrar a mesa.

## Pedido
```mermaid
stateDiagram-v2
    [*] --> RECEBIDO
    RECEBIDO --> EM_PREPARO
    RECEBIDO --> PRONTO
    RECEBIDO --> ENTREGUE
    EM_PREPARO --> PRONTO
    EM_PREPARO --> ENTREGUE
    PRONTO --> ENTREGUE
    RECEBIDO --> CANCELADO: caixa/admin, motivo
    EM_PREPARO --> CANCELADO: caixa/admin, motivo
    PRONTO --> CANCELADO: caixa/admin, motivo
```
Toda mudança grava `order_status_history` (de, para, quem, motivo, quando).
