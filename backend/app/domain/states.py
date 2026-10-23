"""Máquinas de estado explícitas. Qualquer transição fora destas tabelas é rejeitada."""
from __future__ import annotations

import enum

from app.core.errors import AppError


class TableStatus(str, enum.Enum):
    LIVRE = "LIVRE"
    OCUPADA = "OCUPADA"
    ENCERRAMENTO_SOLICITADO = "ENCERRAMENTO_SOLICITADO"


class SessionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RequestType(str, enum.Enum):
    CHAMAR_ATENDENTE = "CHAMAR_ATENDENTE"
    NOVO_PEDIDO = "NOVO_PEDIDO"
    PEDIR_CONTA = "PEDIR_CONTA"


class RequestStatus(str, enum.Enum):
    PENDENTE = "PENDENTE"
    ASSUMIDA = "ASSUMIDA"
    EM_ATENDIMENTO = "EM_ATENDIMENTO"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


ACTIVE_REQUEST_STATUSES = (RequestStatus.PENDENTE, RequestStatus.ASSUMIDA, RequestStatus.EM_ATENDIMENTO)


class OrderStatus(str, enum.Enum):
    RECEBIDO = "RECEBIDO"
    EM_PREPARO = "EM_PREPARO"
    PRONTO = "PRONTO"
    ENTREGUE = "ENTREGUE"
    CANCELADO = "CANCELADO"


PENDING_ORDER_STATUSES = (OrderStatus.RECEBIDO, OrderStatus.EM_PREPARO, OrderStatus.PRONTO)


TABLE_TRANSITIONS: dict[TableStatus, set[TableStatus]] = {
    TableStatus.LIVRE: {TableStatus.OCUPADA},
    TableStatus.OCUPADA: {TableStatus.ENCERRAMENTO_SOLICITADO, TableStatus.LIVRE},
    TableStatus.ENCERRAMENTO_SOLICITADO: {TableStatus.OCUPADA, TableStatus.LIVRE},
}

REQUEST_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.PENDENTE: {
        RequestStatus.ASSUMIDA, RequestStatus.EM_ATENDIMENTO, RequestStatus.CONCLUIDA,
        RequestStatus.CANCELADA,
    },
    RequestStatus.ASSUMIDA: {RequestStatus.EM_ATENDIMENTO, RequestStatus.CONCLUIDA, RequestStatus.CANCELADA},
    RequestStatus.EM_ATENDIMENTO: {RequestStatus.CONCLUIDA, RequestStatus.CANCELADA},
    RequestStatus.CONCLUIDA: set(),
    RequestStatus.CANCELADA: set(),
}

ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.RECEBIDO: {OrderStatus.EM_PREPARO, OrderStatus.PRONTO, OrderStatus.ENTREGUE, OrderStatus.CANCELADO},
    OrderStatus.EM_PREPARO: {OrderStatus.PRONTO, OrderStatus.ENTREGUE, OrderStatus.CANCELADO},
    OrderStatus.PRONTO: {OrderStatus.ENTREGUE, OrderStatus.CANCELADO},
    OrderStatus.ENTREGUE: set(),
    OrderStatus.CANCELADO: set(),
}


def ensure_transition(table: dict, current: enum.Enum, target: enum.Enum, what: str) -> None:
    if target not in table[current]:
        raise AppError(
            409,
            "invalid_transition",
            f"{what}: transição {current.value} → {target.value} não permitida.",
            {"current": current.value, "target": target.value},
        )
