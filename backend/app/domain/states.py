"""Estados do domínio."""

from __future__ import annotations

import enum

from app.core.errors import AppError


class TableStatus(str, enum.Enum):
    LIVRE = "LIVRE"
    AGUARDANDO_LIBERACAO = "AGUARDANDO_LIBERACAO"
    OCUPADA = "OCUPADA"


class SessionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RequestType(str, enum.Enum):
    LIBERAR_MESA = "LIBERAR_MESA"
    CHAMAR_ATENDENTE = "CHAMAR_ATENDENTE"
    NOVO_PEDIDO = "NOVO_PEDIDO"
    PEDIR_CONTA = "PEDIR_CONTA"


class RequestStatus(str, enum.Enum):
    PENDENTE = "PENDENTE"
    EM_ATENDIMENTO = "EM_ATENDIMENTO"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


ACTIVE_REQUEST_STATUSES = (RequestStatus.PENDENTE, RequestStatus.EM_ATENDIMENTO)


class TagStatus(str, enum.Enum):
    """Ciclo da etiqueta NFC de uma mesa. O servidor define a URL; ninguém a digita."""

    PENDENTE = "PENDENTE"  # mesa criada, aguardando aproximar a etiqueta
    GRAVANDO = "GRAVANDO"  # celular do administrador está gravando
    GRAVADA = "GRAVADA"  # URL gravada e conferida na leitura; etiqueta ainda regravável
    TRAVADA = "TRAVADA"  # bloqueada fisicamente (somente leitura, irreversível)
    FALHA = "FALHA"  # gravação ou conferência falhou
    SUBSTITUIDA = "SUBSTITUIDA"  # trocada por outra etiqueta ou nova gravação


LIVE_TAG_STATUSES = (TagStatus.PENDENTE, TagStatus.GRAVANDO, TagStatus.GRAVADA, TagStatus.TRAVADA)
UID_TAG_STATUSES = (TagStatus.GRAVADA, TagStatus.TRAVADA)

TABLE_TRANSITIONS: dict[TableStatus, set[TableStatus]] = {
    TableStatus.LIVRE: {TableStatus.AGUARDANDO_LIBERACAO, TableStatus.OCUPADA},
    TableStatus.AGUARDANDO_LIBERACAO: {TableStatus.OCUPADA, TableStatus.LIVRE},
    TableStatus.OCUPADA: {TableStatus.LIVRE},
}

REQUEST_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.PENDENTE: {RequestStatus.EM_ATENDIMENTO, RequestStatus.CONCLUIDA, RequestStatus.CANCELADA},
    RequestStatus.EM_ATENDIMENTO: {RequestStatus.CONCLUIDA, RequestStatus.CANCELADA},
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


def can_advance_request(req_type: RequestType, current: RequestStatus) -> RequestStatus | None:
    """Retorna o próximo estado ao avançar a solicitação, ou None se já estiver encerrada."""
    if req_type == RequestType.NOVO_PEDIDO:
        if current == RequestStatus.PENDENTE:
            return RequestStatus.EM_ATENDIMENTO
        if current == RequestStatus.EM_ATENDIMENTO:
            return RequestStatus.CONCLUIDA
        return None

    if current == RequestStatus.PENDENTE:
        return RequestStatus.CONCLUIDA
    return None


TAG_TRANSITIONS: dict[TagStatus, set[TagStatus]] = {
    TagStatus.PENDENTE: {TagStatus.GRAVANDO, TagStatus.FALHA, TagStatus.SUBSTITUIDA},
    TagStatus.GRAVANDO: {TagStatus.GRAVADA, TagStatus.FALHA, TagStatus.SUBSTITUIDA},
    TagStatus.GRAVADA: {TagStatus.TRAVADA, TagStatus.GRAVANDO, TagStatus.FALHA, TagStatus.SUBSTITUIDA},
    TagStatus.TRAVADA: {TagStatus.SUBSTITUIDA},
    TagStatus.FALHA: {TagStatus.GRAVANDO, TagStatus.SUBSTITUIDA},
    TagStatus.SUBSTITUIDA: set(),
}
