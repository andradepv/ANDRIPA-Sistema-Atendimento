from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.permissions import Perm, Role, has_perm
from app.core.security import constant_time_eq, token_hash
from app.db.session import get_db
from app.domain.states import SessionStatus
from app.models import CustomerToken, DiningTable, Establishment, StaffSession, TableSession, User

STAFF_COOKIE = "andripa_staff"
CSRF_COOKIE = "andripa_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class StaffCtx:
    user: User
    session: StaffSession

    @property
    def establishment_id(self) -> uuid.UUID:
        return self.user.establishment_id

    @property
    def role(self) -> Role:
        return self.user.role

    def can(self, perm: Perm) -> bool:
        return has_perm(self.user.role, perm)


async def load_staff_session(db: AsyncSession, raw_token: str | None) -> StaffSession | None:
    """Valida token de funcionário (usado por HTTP e WebSocket)."""
    if not raw_token or len(raw_token) > 200:
        return None
    s = (await db.execute(
        select(StaffSession).where(StaffSession.token_hash == token_hash(raw_token))
    )).scalar_one_or_none()
    if s is None or s.revoked_at is not None:
        return None
    now = utcnow()
    idle = timedelta(minutes=get_settings().staff_session_idle_minutes)
    if s.expires_at <= now or s.last_seen_at + idle <= now or not s.user.active:
        return None
    return s


async def get_staff(request: Request, db: AsyncSession = Depends(get_db)) -> StaffCtx:
    s = await load_staff_session(db, request.cookies.get(STAFF_COOKIE))
    if s is None:
        raise AppError(401, "unauthenticated", "Sessão expirada ou inválida. Faça login novamente.")
    if request.method not in SAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        if not header or not constant_time_eq(header, s.csrf_token):
            raise AppError(403, "csrf_failed", "Falha na verificação CSRF. Recarregue a página.")
    now = utcnow()
    if now - s.last_seen_at > timedelta(seconds=60):
        s.last_seen_at = now
        await db.commit()
    return StaffCtx(user=s.user, session=s)


def require(perm: Perm):
    async def _dep(ctx: StaffCtx = Depends(get_staff)) -> StaffCtx:
        if not ctx.can(perm):
            raise AppError(403, "forbidden", "Você não tem permissão para esta operação.",
                           {"required": perm.value})
        return ctx

    return _dep


@dataclass
class CustomerCtx:
    token: CustomerToken
    session: TableSession
    table: DiningTable
    establishment: Establishment


async def load_customer(db: AsyncSession, raw: str | None, *, lock: bool = False) -> CustomerCtx | None:
    if not raw or len(raw) > 200:
        return None
    tok = (await db.execute(
        select(CustomerToken).where(CustomerToken.token_hash == token_hash(raw))
    )).scalar_one_or_none()
    if tok is None or tok.revoked_at is not None or tok.expires_at <= utcnow():
        return None
    q = select(TableSession).where(TableSession.id == tok.session_id)
    if lock:
        q = q.with_for_update(of=TableSession).execution_options(populate_existing=True)
    sess = (await db.execute(q)).unique().scalar_one()
    if sess.status != SessionStatus.OPEN:
        return None
    est = await db.get(Establishment, sess.establishment_id)
    assert est is not None
    return CustomerCtx(token=tok, session=sess, table=sess.table, establishment=est)


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def get_customer(request: Request, db: AsyncSession = Depends(get_db)) -> CustomerCtx:
    ctx = await load_customer(db, _bearer(request))
    if ctx is None:
        raise AppError(401, "session_ended",
                       "Esta sessão da mesa foi encerrada ou não é válida. Leia o QR Code novamente.")
    return ctx
