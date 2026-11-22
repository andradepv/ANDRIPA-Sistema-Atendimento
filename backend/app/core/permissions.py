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
    TABLES_CLOSE = "tables.close"
    TABLES_MANAGE = "tables.manage"
    REQUESTS_HANDLE = "requests.handle"
    HISTORY_VIEW = "history.view"
    MENU_MANAGE = "menu.manage"
    NOTICES_MANAGE = "notices.manage"
    USERS_MANAGE = "users.manage"
    AUDIT_VIEW = "audit.view"
    SETTINGS_MANAGE = "settings.manage"
    TABLES_PROVISION = "tables.provision"  # criar mesa + gravar/travar etiqueta NFC (só administrador)
    LAYOUTS_MANAGE = "layouts.manage"      # editar e ativar plantas (templates) do salão (só administrador)


# Atendente: libera mesas e resolve chamados e pedidos.
_ATENDENTE = {Perm.TABLES_VIEW, Perm.TABLES_OPEN, Perm.REQUESTS_HANDLE}

# Caixa: além disso, finaliza a conta (encerra a mesa) e consulta o histórico.
_CAIXA = _ATENDENTE | {Perm.TABLES_CLOSE, Perm.HISTORY_VIEW}

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
