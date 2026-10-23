from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CSRF_COOKIE, STAFF_COOKIE, StaffCtx, get_staff, utcnow
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.permissions import perms_for
from app.core.ratelimit import client_ip, hit
from app.core.security import hash_secret, new_token, token_hash, verify_secret
from app.db.session import get_db
from app.models import Establishment, StaffSession, User
from app.schemas import ChangeOwnCredentials, EstablishmentOut, LoginIn, MeOut
from app.services.audit import audit
from app.services.events import STAFF, emit
from app.services.serializers import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(resp: Response, token: str, csrf: str, max_age: int) -> None:
    secure = get_settings().cookie_secure
    resp.set_cookie(STAFF_COOKIE, token, max_age=max_age, httponly=True, secure=secure, samesite="strict", path="/api")
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure, samesite="strict", path="/")


async def _me(db: AsyncSession, user: User, csrf: str) -> MeOut:
    est = await db.get(Establishment, user.establishment_id)
    return MeOut(user=user_out(user), permissions=perms_for(user.role),
                 establishment=EstablishmentOut.model_validate(est), csrf_token=csrf)


@router.post("/login", response_model=MeOut)
async def login(data: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> MeOut:
    ip = client_ip(request)
    await hit(f"login:ip:{ip}", 20, 300)
    await hit(f"login:email:{data.email}", 8, 300)
    user = (await db.execute(select(User).where(User.email == data.email))).scalar_one_or_none()
    ok = verify_secret(data.password, user.password_hash if user else None)
    if not ok or user is None or not user.active:
        if user is not None:
            audit(db, establishment_id=user.establishment_id, actor_id=user.id, action="auth.login_failed", ip=ip)
            await db.commit()
        raise AppError(401, "invalid_credentials", "E-mail ou senha incorretos.")
    s = get_settings()
    token, csrf = new_token(), secrets.token_urlsafe(24)
    now = utcnow()
    db.add(StaffSession(user_id=user.id, token_hash=token_hash(token), csrf_token=csrf,
                        expires_at=now + timedelta(hours=s.staff_session_ttl_hours), last_seen_at=now,
                        user_agent=(request.headers.get("user-agent") or "")[:255]))
    audit(db, establishment_id=user.establishment_id, actor_id=user.id, action="auth.login", ip=ip)
    await db.commit()
    _set_cookies(response, token, csrf, s.staff_session_ttl_hours * 3600)
    return await _me(db, user, csrf)


@router.post("/logout", status_code=204)
async def logout(response: Response, ctx: StaffCtx = Depends(get_staff), db: AsyncSession = Depends(get_db)) -> Response:
    sess = await db.get(StaffSession, ctx.session.id)
    assert sess is not None
    sess.revoked_at = utcnow()
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="auth.logout")
    emit(db, ctx.establishment_id, "staff.session_revoked", {"staff_session_ids": [str(sess.id)]}, audience=())
    await db.commit()
    response.status_code = 204
    response.delete_cookie(STAFF_COOKIE, path="/api")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@router.post("/logout-all", status_code=204)
async def logout_all(response: Response, ctx: StaffCtx = Depends(get_staff), db: AsyncSession = Depends(get_db)) -> Response:
    ids = (await db.execute(update(StaffSession).where(StaffSession.user_id == ctx.user.id,
                                                       StaffSession.revoked_at.is_(None))
                            .values(revoked_at=utcnow()).returning(StaffSession.id))).scalars().all()
    emit(db, ctx.establishment_id, "staff.session_revoked", {"staff_session_ids": [str(i) for i in ids]}, audience=())
    audit(db, establishment_id=ctx.establishment_id, actor_id=ctx.user.id, action="auth.logout_all")
    await db.commit()
    response.status_code = 204
    response.delete_cookie(STAFF_COOKIE, path="/api")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@router.get("/me", response_model=MeOut)
async def me(ctx: StaffCtx = Depends(get_staff), db: AsyncSession = Depends(get_db)) -> MeOut:
    return await _me(db, ctx.user, ctx.session.csrf_token)


@router.post("/credentials", status_code=204)
async def change_credentials(data: ChangeOwnCredentials, request: Request, ctx: StaffCtx = Depends(get_staff),
                             db: AsyncSession = Depends(get_db)) -> Response:
    await hit(f"cred:{ctx.user.id}", 10, 600)
    user = await db.get(User, ctx.user.id)
    assert user is not None
    if not verify_secret(data.current_password, user.password_hash):
        raise AppError(403, "confirmation_failed", "Senha atual incorreta.")
    if data.new_password:
        user.password_hash = hash_secret(data.new_password)
        # Troca de senha revoga as outras sessões.
        ids = (await db.execute(update(StaffSession).where(
            StaffSession.user_id == user.id, StaffSession.id != ctx.session.id, StaffSession.revoked_at.is_(None))
            .values(revoked_at=utcnow()).returning(StaffSession.id))).scalars().all()
        emit(db, ctx.establishment_id, "staff.session_revoked", {"staff_session_ids": [str(i) for i in ids]},
             audience=())
    if data.new_pin:
        user.pin_hash = hash_secret(data.new_pin)
    audit(db, establishment_id=ctx.establishment_id, actor_id=user.id, action="auth.change_credentials",
          details={"password": bool(data.new_password), "pin": bool(data.new_pin)}, ip=client_ip(request))
    await db.commit()
    return Response(status_code=204)


__all__ = ["router", "STAFF"]
