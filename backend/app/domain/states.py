"""Estados do domínio. O fluxo é propositalmente curto: cada solicitação só é aberta e depois resolvida."""
from __future__ import annotations

import enum

from app.core.errors import AppError


class TableStatus(str, enum.Enum):
    LIVRE = "LIVRE"
    OCUPADA = "OCUPADA"


class SessionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RequestType(str, enum.Enum):
    CHAMAR_ATENDENTE = "CHAMAR_ATENDENTE"
    NOVO_PEDIDO = "NOVO_PEDIDO"
    PEDIR_CONTA = "PEDIR_CONTA"


class RequestStatus(str, enum.Enum):
    PENDENTE = "PENDENTE"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


ACTIVE_REQUEST_STATUSES = (RequestStatus.PENDENTE,)


class TagStatus(str, enum.Enum):
    """Ciclo da etiqueta NFC de uma mesa. O servidor define a URL; ninguém a digita."""

    PENDENTE = "PENDENTE"        # mesa criada, aguardando aproximar a etiqueta
    GRAVANDO = "GRAVANDO"        # celular do administrador está gravando
    GRAVADA = "GRAVADA"          # URL gravada e conferida na leitura; etiqueta ainda regravável
    TRAVADA = "TRAVADA"          # bloqueada fisicamente (somente leitura, irreversível)
    FALHA = "FALHA"              # gravação ou conferência falhou
    SUBSTITUIDA = "SUBSTITUIDA"  # trocada por outra etiqueta ou nova gravação


LIVE_TAG_STATUSES = (TagStatus.PENDENTE, TagStatus.GRAVANDO, TagStatus.GRAVADA, TagStatus.TRAVADA)
UID_TAG_STATUSES = (TagStatus.GRAVADA, TagStatus.TRAVADA)

TABLE_TRANSITIONS: dict[TableStatus, set[TableStatus]] = {
    TableStatus.LIVRE: {TableStatus.OCUPADA},
    TableStatus.OCUPADA: {TableStatus.LIVRE},
}

REQUEST_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.PENDENTE: {RequestStatus.CONCLUIDA, RequestStatus.CANCELADA},
    RequestStatus.CONCLUIDA: set(),
    RequestStatus.CANCELADA: set(),
}

def ensure_transition(table: dict, current: enum.Enum, target: enum.Enum, what: str) -> None:
    if target not in table[current]:
        raise AppError(
            409,
            "invalid_transition",
            f"{what}: transição {current.value} → {target.value} não permitida.",
            {"current": current.value, "target": target.value},
        )


TAG_TRANSITIONS: dict[TagStatus, set[TagStatus]] = {
    TagStatus.PENDENTE: {TagStatus.GRAVANDO, TagStatus.FALHA, TagStatus.SUBSTITUIDA},
    TagStatus.GRAVANDO: {TagStatus.GRAVADA, TagStatus.FALHA, TagStatus.SUBSTITUIDA},
    TagStatus.GRAVADA: {TagStatus.TRAVADA, TagStatus.GRAVANDO, TagStatus.FALHA, TagStatus.SUBSTITUIDA},
    TagStatus.TRAVADA: {TagStatus.SUBSTITUIDA},
    TagStatus.FALHA: {TagStatus.GRAVANDO, TagStatus.SUBSTITUIDA},
    TagStatus.SUBSTITUIDA: set(),
}
