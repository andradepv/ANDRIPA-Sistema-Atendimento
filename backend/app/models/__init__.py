"""Modelos SQLAlchemy 2.x. Datas sempre em UTC (timestamptz). PKs UUID não enumeráveis."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.permissions import Role
from app.domain.states import RequestStatus, RequestType, SessionStatus, TableStatus, TagStatus

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    # Busca valores gerados pelo servidor (ex.: created_at) via RETURNING.
    __mapper_args__ = {"eager_defaults": True}


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(
        e, name=name, native_enum=False, create_constraint=True, length=32,
        values_callable=lambda x: [i.value for i in x], validate_strings=True,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _est_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("establishments.id", ondelete="RESTRICT"), nullable=False, index=True)


class Establishment(Base):
    __tablename__ = "establishments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Sao_Paulo")
    join_code_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(lazy="joined")


class DiningTable(Base):
    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("establishment_id", "number", name="uq_tables_est_number"),
                      CheckConstraint("number > 0", name="number_positive"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(80))
    public_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    status: Mapped[TableStatus] = mapped_column(_enum(TableStatus, "table_status"), nullable=False,
                                                default=TableStatus.LIVRE)
    current_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("table_sessions.id", use_alter=True, name="fk_tables_current_session"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TableSession(Base):
    __tablename__ = "table_sessions"
    __table_args__ = (
        Index("uq_open_session_per_table", "table_id", unique=True,
              postgresql_where=text("status = 'OPEN'")),
        Index("ix_table_sessions_est_status_opened", "establishment_id", "status", "opened_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id", ondelete="RESTRICT"), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[SessionStatus] = mapped_column(_enum(SessionStatus, "session_status"), nullable=False,
                                                  default=SessionStatus.OPEN)
    join_code: Mapped[str] = mapped_column(String(8), nullable=False)
    opened_at: Mapped[datetime] = _created()
    opened_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    close_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    table: Mapped[DiningTable] = relationship(foreign_keys=[table_id], lazy="joined")
    opened_by: Mapped[User] = relationship(foreign_keys=[opened_by_id], lazy="joined")


class CustomerToken(Base):
    __tablename__ = "customer_tokens"
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("table_sessions.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        # Um chamado ativo por tipo e sessão: repetir o toque devolve o chamado já aberto.
        Index("uq_active_request_per_type", "session_id", "type", unique=True,
              postgresql_where=text("status IN ('PENDENTE','ASSUMIDA','EM_ATENDIMENTO')")),
        Index("ix_service_requests_est_status_created", "establishment_id", "status", "created_at"),
        CheckConstraint("priority BETWEEN 0 AND 3", name="priority_range"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("table_sessions.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id"), nullable=False)
    type: Mapped[RequestType] = mapped_column(_enum(RequestType, "request_type"), nullable=False)
    status: Mapped[RequestStatus] = mapped_column(_enum(RequestStatus, "request_status"), nullable=False,
                                                  default=RequestStatus.PENDENTE)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(280))
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="CLIENTE")
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    table: Mapped[DiningTable] = relationship(lazy="joined")
    assigned_to: Mapped[User | None] = relationship(lazy="joined")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "id", postgresql_where=text("published_at IS NULL")),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    establishment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


class TableTag(Base):
    """Etiqueta NFC de uma mesa. A URL gravada vem sempre do servidor (nunca digitada)."""

    __tablename__ = "table_tags"
    __table_args__ = (
        # No máximo uma etiqueta "viva" por mesa; tentativas antigas ficam como FALHA/SUBSTITUIDA.
        Index("uq_live_tag_per_table", "table_id", unique=True,
              postgresql_where=text("status IN ('PENDENTE','GRAVANDO','GRAVADA','TRAVADA')")),
        # Um mesmo chip físico (UID) não pode representar duas mesas ao mesmo tempo.
        Index("uq_tag_uid_in_use", "establishment_id", "uid", unique=True,
              postgresql_where=text("uid IS NOT NULL AND status IN ('GRAVADA','TRAVADA')")),
        Index("ix_table_tags_est_updated", "establishment_id", "updated_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[TagStatus] = mapped_column(_enum(TagStatus, "tag_status"), nullable=False,
                                              default=TagStatus.PENDENTE)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    uid: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(280))
    started_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    lock_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    table: Mapped[DiningTable] = relationship(foreign_keys=[table_id], lazy="joined")
    started_by: Mapped[User] = relationship(foreign_keys=[started_by_id], lazy="joined")


class FloorLayout(Base):
    """Planta (template) do salão. Só uma por estabelecimento fica ativa; só o administrador altera."""

    __tablename__ = "floor_layouts"
    __table_args__ = (
        UniqueConstraint("establishment_id", "name", name="uq_floor_layouts_est_name"),
        Index("uq_active_layout_per_est", "establishment_id", unique=True, postgresql_where=text("is_active")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    items: Mapped[list[FloorLayoutItem]] = relationship(lazy="selectin", cascade="all, delete-orphan",
                                                         order_by="FloorLayoutItem.y, FloorLayoutItem.x")


class FloorLayoutItem(Base):
    __tablename__ = "floor_layout_items"
    __table_args__ = (
        UniqueConstraint("layout_id", "x", "y", name="uq_floor_item_cell"),
        CheckConstraint("x >= 0 AND x < 24 AND y >= 0 AND y < 16", name="cell_in_grid"),
    )
    layout_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("floor_layouts.id", ondelete="CASCADE"), primary_key=True)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id", ondelete="CASCADE"), primary_key=True)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_est_created", "establishment_id", "created_at"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # STAFF | CLIENTE | SISTEMA
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()

    actor: Mapped[User | None] = relationship(lazy="joined")
