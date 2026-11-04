"""Estados do domínio. O fluxo é propositalmente curto: cada solicitação só é aberta e depois resolvida."""
from __future__ import annotations

import enum


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
    # Atendido (chamado), repassado à cozinha (pedido) ou conta finalizada (conta).
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"
