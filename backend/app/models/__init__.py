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
from app.domain.states import OrderStatus, RequestStatus, RequestType, SessionStatus, TableStatus

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    # Busca valores gerados pelo servidor (created_at, número do pedido) via RETURNING.
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
    orders_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    subtotal_cents: Mapped[int | None] = mapped_column(Integer)
    discount_cents: Mapped[int | None] = mapped_column(Integer)
    total_cents: Mapped[int | None] = mapped_column(Integer)
    payment_method: Mapped[str | None] = mapped_column(String(32))
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coupons.id"))
    close_note: Mapped[str | None] = mapped_column(String(500))
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
        # Um chamado ativo por tipo e sessão (pedidos geram um chamado por pedido).
        Index("uq_active_request_per_type", "session_id", "type", unique=True,
              postgresql_where=text(
                  "status IN ('PENDENTE','ASSUMIDA','EM_ATENDIMENTO') AND type <> 'NOVO_PEDIDO'")),
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
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", use_alter=True,
                                                                  name="fk_service_requests_order"))
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="CLIENTE")
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    table: Mapped[DiningTable] = relationship(lazy="joined")
    assigned_to: Mapped[User | None] = relationship(lazy="joined")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("establishment_id", "name", name="uq_categories_est_name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("price_cents >= 0", name="price_non_negative"),
                      Index("ix_products_est_category", "establishment_id", "category_id"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    option_groups: Mapped[list[OptionGroup]] = relationship(
        back_populates="product", order_by="OptionGroup.position", lazy="selectin",
        cascade="all, delete-orphan",
    )


class OptionGroup(Base):
    __tablename__ = "option_groups"
    __table_args__ = (CheckConstraint("min_select >= 0 AND max_select >= min_select AND max_select >= 1",
                                      name="select_range"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    min_select: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_select: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped[Product] = relationship(back_populates="option_groups")
    options: Mapped[list[ProductOption]] = relationship(
        back_populates="group", order_by="ProductOption.position", lazy="selectin",
        cascade="all, delete-orphan",
    )


class ProductOption(Base):
    __tablename__ = "product_options"
    __table_args__ = (CheckConstraint("price_cents >= 0", name="price_non_negative"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("option_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    group: Mapped[OptionGroup] = relationship(back_populates="options")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_est_status_created", "establishment_id", "status", "created_at"),
                      CheckConstraint("total_cents >= 0", name="total_non_negative"))
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("table_sessions.id", ondelete="RESTRICT"),
                                                  nullable=False, index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tables.id"), nullable=False)
    number: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                        server_default=text("nextval('order_number_seq')"))
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus, "order_status"), nullable=False,
                                                default=OrderStatus.RECEBIDO)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="CLIENTE")
    note: Mapped[str | None] = mapped_column(String(280))
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    items: Mapped[list[OrderItem]] = relationship(back_populates="order", lazy="selectin",
                                                  cascade="all, delete-orphan")
    table: Mapped[DiningTable] = relationship(lazy="joined")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 50", name="quantity_range"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(String(280))
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    id: Mapped[uuid.UUID] = _uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(280))
    created_at: Mapped[datetime] = _created()


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


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    endpoint: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    consent_marketing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = _created()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PromotionKind(str, enum.Enum):
    BANNER = "BANNER"
    EVENTO = "EVENTO"
    CAMPANHA = "CAMPANHA"


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="period_valid"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    kind: Mapped[PromotionKind] = mapped_column(_enum(PromotionKind, "promotion_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(500))
    conditions: Mapped[str | None] = mapped_column(String(500))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class DiscountType(str, enum.Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("establishment_id", "code", name="uq_coupons_est_code"),
        CheckConstraint("ends_at > starts_at", name="period_valid"),
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("discount_type <> 'PERCENT' OR value <= 100", name="percent_max"),
        CheckConstraint("max_uses IS NULL OR uses_count <= max_uses", name="uses_within_limit"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    establishment_id: Mapped[uuid.UUID] = _est_fk()
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(280))
    discount_type: Mapped[DiscountType] = mapped_column(_enum(DiscountType, "discount_type"), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)  # % ou centavos
    min_order_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


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
