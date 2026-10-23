"""Fonte única das regras de autorização (RBAC).

O papel do usuário vem sempre do banco (via sessão autenticada), nunca do frontend.
"""
from __future__ import annotations

import enum


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    CAIXA = "CAIXA"
    ATENDENTE = "ATENDENTE"


class Perm(str, enum.Enum):
    TABLES_VIEW = "tables.view"
    TABLES_OPEN = "tables.open"
    TABLES_REQUEST_CLOSE = "tables.request_close"
    TABLES_CLOSE = "tables.close"
    TABLES_MANAGE = "tables.manage"
    REQUESTS_VIEW = "requests.view"
    REQUESTS_HANDLE = "requests.handle"
    REQUESTS_PRIORITIZE = "requests.prioritize"
    ORDERS_VIEW = "orders.view"
    ORDERS_UPDATE_STATUS = "orders.update_status"
    ORDERS_CANCEL = "orders.cancel"
    CASH_VIEW = "cash.view"
    HISTORY_VIEW = "history.view"
    MENU_MANAGE = "menu.manage"
    PROMOTIONS_MANAGE = "promotions.manage"
    PUSH_SEND = "push.send"
    USERS_MANAGE = "users.manage"
    AUDIT_VIEW = "audit.view"
    SETTINGS_MANAGE = "settings.manage"


_ATENDENTE = {
    Perm.TABLES_VIEW,
    Perm.TABLES_OPEN,
    Perm.TABLES_REQUEST_CLOSE,
    Perm.REQUESTS_VIEW,
    Perm.REQUESTS_HANDLE,
    Perm.ORDERS_VIEW,
    Perm.ORDERS_UPDATE_STATUS,
}

_CAIXA = _ATENDENTE | {
    Perm.TABLES_CLOSE,
    Perm.REQUESTS_PRIORITIZE,
    Perm.ORDERS_CANCEL,
    Perm.CASH_VIEW,
    Perm.HISTORY_VIEW,
}

# O administrador possui todas as permissões, inclusive as que forem criadas no futuro.
ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.ATENDENTE: frozenset(_ATENDENTE),
    Role.CAIXA: frozenset(_CAIXA),
    Role.ADMIN: frozenset(Perm),
}


def has_perm(role: Role | str, perm: Perm) -> bool:
    return perm in ROLE_PERMISSIONS[Role(role)]


def perms_for(role: Role | str) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS[Role(role)])
