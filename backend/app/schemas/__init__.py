"""Contratos Pydantic de entrada e saída da API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.permissions import Role
from app.domain.states import OrderStatus, RequestStatus, RequestType, TableStatus
from app.models import DiscountType, PromotionKind

Str80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Str120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
OptStr280 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)] | None
OptStr1000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254,
                                         pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
HttpsUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500,
                                            pattern=r"^https://[^\s<>\"']+$")] | None


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- auth / users ----------
class LoginIn(In):
    email: Email
    password: str = Field(min_length=1, max_length=256)


class UserOut(Out):
    id: uuid.UUID
    name: str
    email: str
    role: Role
    active: bool
    has_pin: bool = False


class MeOut(BaseModel):
    user: UserOut
    permissions: list[str]
    establishment: EstablishmentOut
    csrf_token: str


class EstablishmentOut(Out):
    id: uuid.UUID
    name: str
    timezone: str
    join_code_required: bool
    orders_enabled: bool


class EstablishmentPatch(In):
    name: Str120 | None = None
    timezone: Annotated[str, StringConstraints(max_length=64)] | None = None
    join_code_required: bool | None = None
    orders_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError("Fuso horário inválido") from e
        return v


Password = Annotated[str, StringConstraints(min_length=10, max_length=256)]
Pin = Annotated[str, StringConstraints(pattern=r"^\d{4,8}$")]


class UserCreate(In):
    name: Str120
    email: Email
    role: Role
    password: Password
    pin: Pin | None = None


class UserPatch(In):
    name: Str120 | None = None
    role: Role | None = None
    active: bool | None = None
    password: Password | None = None
    pin: Pin | None = None
    clear_pin: bool = False


class ChangeOwnCredentials(In):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: Password | None = None
    new_pin: Pin | None = None


# ---------- tables / sessions ----------
class TableCreate(In):
    number: int = Field(ge=1, le=9999)
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None


class TablePatch(In):
    number: int | None = Field(default=None, ge=1, le=9999)
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    active: bool | None = None


class SessionBrief(Out):
    id: uuid.UUID
    label: str | None
    opened_at: datetime
    opened_by_name: str
    join_code: str | None = None
    close_requested_at: datetime | None


class TableOut(Out):
    id: uuid.UUID
    number: int
    name: str | None
    status: TableStatus
    active: bool
    public_url: str
    version: int
    session: SessionBrief | None = None
    pending_requests: int = 0
    pending_orders: int = 0


class OpenTableIn(In):
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    confirm_secret: str = Field(min_length=4, max_length=256, description="PIN pessoal ou senha")


class CloseSessionIn(In):
    payment_method: Literal["DINHEIRO", "CARTAO_CREDITO", "CARTAO_DEBITO", "PIX", "OUTRO"]
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    pending_orders_policy: Literal["block", "cancel_pending"] = "block"
    note: OptStr280 = None
    expected_version: int | None = None

    @model_validator(mode="after")
    def _reason(self) -> CloseSessionIn:
        if self.pending_orders_policy == "cancel_pending" and not self.note:
            raise ValueError("Informe o motivo ao cancelar pedidos pendentes.")
        return self


# ---------- service requests ----------
class ServiceRequestOut(Out):
    id: uuid.UUID
    session_id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    table_name: str | None
    type: RequestType
    status: RequestStatus
    priority: int
    note: str | None
    order_id: uuid.UUID | None
    origin: str
    assigned_to_id: uuid.UUID | None
    assigned_to_name: str | None
    created_at: datetime
    updated_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
    version: int


class CustomerRequestIn(In):
    type: Literal["CHAMAR_ATENDENTE", "PEDIR_CONTA"]
    note: OptStr280 = None


class PriorityIn(In):
    priority: int = Field(ge=0, le=3)


# ---------- menu ----------
class CategoryIn(In):
    name: Str80
    position: int = Field(default=0, ge=0, le=10_000)
    active: bool = True


class CategoryPatch(In):
    name: Str80 | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    active: bool | None = None


class CategoryOut(Out):
    id: uuid.UUID
    name: str
    position: int
    active: bool


class OptionIn(In):
    id: uuid.UUID | None = None
    name: Str80
    price_cents: int = Field(default=0, ge=0, le=1_000_000)
    active: bool = True


class OptionGroupIn(In):
    id: uuid.UUID | None = None
    name: Str80
    min_select: int = Field(default=0, ge=0, le=20)
    max_select: int = Field(default=1, ge=1, le=20)
    options: list[OptionIn] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _range(self) -> OptionGroupIn:
        if self.max_select < self.min_select:
            raise ValueError("max_select deve ser >= min_select")
        return self


class ProductIn(In):
    category_id: uuid.UUID
    name: Str120
    description: OptStr1000 = None
    price_cents: int = Field(ge=0, le=10_000_000)
    image_url: HttpsUrl = None
    available: bool = True
    active: bool = True
    position: int = Field(default=0, ge=0, le=10_000)
    option_groups: list[OptionGroupIn] = Field(default_factory=list, max_length=10)


class ProductPatch(In):
    category_id: uuid.UUID | None = None
    name: Str120 | None = None
    description: OptStr1000 = None
    price_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    image_url: HttpsUrl = None
    available: bool | None = None
    active: bool | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    option_groups: list[OptionGroupIn] | None = Field(default=None, max_length=10)


class OptionOut(Out):
    id: uuid.UUID
    name: str
    price_cents: int
    active: bool


class OptionGroupOut(Out):
    id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: list[OptionOut]


class ProductOut(Out):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str | None
    price_cents: int
    image_url: str | None
    available: bool
    active: bool
    position: int
    option_groups: list[OptionGroupOut]


class MenuCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    products: list[ProductOut]


# ---------- orders ----------
class OrderItemIn(In):
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=50)
    option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    notes: OptStr280 = None


class OrderIn(In):
    items: list[OrderItemIn] = Field(min_length=1, max_length=40)
    note: OptStr280 = None


class OrderItemOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    unit_price_cents: int
    quantity: int
    options: list[dict]
    notes: str | None
    line_total_cents: int


class OrderOut(Out):
    id: uuid.UUID
    number: int
    session_id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    status: OrderStatus
    origin: str
    note: str | None
    total_cents: int
    created_at: datetime
    updated_at: datetime
    version: int
    items: list[OrderItemOut]


class OrderStatusIn(In):
    status: OrderStatus
    reason: OptStr280 = None
    expected_version: int | None = None


# ---------- session detail / bill ----------
class SessionDetailOut(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    table_name: str | None
    table_status: TableStatus
    label: str | None
    status: str
    join_code: str | None
    opened_at: datetime
    opened_by_name: str
    close_requested_at: datetime | None
    closed_at: datetime | None
    closed_by_name: str | None = None
    payment_method: str | None
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    pending_orders: int
    orders: list[OrderOut]
    requests: list[ServiceRequestOut]
    version: int


class SessionHistoryOut(BaseModel):
    id: uuid.UUID
    table_number: int
    label: str | None
    opened_at: datetime
    closed_at: datetime | None
    opened_by_name: str
    closed_by_name: str | None
    total_cents: int | None
    payment_method: str | None


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- public / customer ----------
class PublicTableOut(BaseModel):
    establishment_name: str
    timezone: str
    table_number: int
    table_name: str | None
    available: bool
    join_code_required: bool
    orders_enabled: bool


class JoinIn(In):
    join_code: Annotated[str, StringConstraints(pattern=r"^\d{4}$")] | None = None


class JoinOut(BaseModel):
    token: str
    expires_at: datetime


class CustomerSessionOut(BaseModel):
    session_id: uuid.UUID
    establishment_name: str
    timezone: str
    table_number: int
    table_name: str | None
    table_status: TableStatus
    orders_enabled: bool
    opened_at: datetime
    requests: list[ServiceRequestOut]
    orders: list[OrderOut]
    total_cents: int
    push_public_key: str | None


# ---------- promotions / coupons ----------
class PromotionIn(In):
    kind: PromotionKind
    title: Str120
    description: OptStr1000 = None
    image_url: HttpsUrl = None
    conditions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    starts_at: datetime
    ends_at: datetime
    active: bool = True

    @model_validator(mode="after")
    def _period(self) -> PromotionIn:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Datas devem incluir fuso horário")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at deve ser posterior a starts_at")
        return self


class PromotionOut(Out):
    id: uuid.UUID
    kind: PromotionKind
    title: str
    description: str | None
    image_url: str | None
    conditions: str | None
    starts_at: datetime
    ends_at: datetime
    active: bool


class CouponIn(In):
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_-]{3,32}$")]
    description: OptStr280 = None
    discount_type: DiscountType
    value: int = Field(gt=0, le=10_000_000)
    min_order_cents: int = Field(default=0, ge=0)
    max_uses: int | None = Field(default=None, ge=1)
    starts_at: datetime
    ends_at: datetime
    active: bool = True

    @model_validator(mode="after")
    def _check(self) -> CouponIn:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Datas devem incluir fuso horário")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at deve ser posterior a starts_at")
        if self.discount_type == DiscountType.PERCENT and self.value > 100:
            raise ValueError("Percentual máximo é 100")
        return self


class CouponOut(Out):
    id: uuid.UUID
    code: str
    description: str | None
    discount_type: DiscountType
    value: int
    min_order_cents: int
    max_uses: int | None
    uses_count: int
    starts_at: datetime
    ends_at: datetime
    active: bool


class CouponValidateIn(In):
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=32)]


class CouponValidateOut(BaseModel):
    valid: bool
    code: str
    description: str | None = None
    discount_type: DiscountType | None = None
    value: int | None = None
    min_order_cents: int | None = None
    estimated_discount_cents: int | None = None
    reason: str | None = None


# ---------- push ----------
class PushKeys(In):
    p256dh: Annotated[str, StringConstraints(max_length=200, pattern=r"^[A-Za-z0-9_\-=]+$")]
    auth: Annotated[str, StringConstraints(max_length=100, pattern=r"^[A-Za-z0-9_\-=]+$")]


class PushSubscriptionIn(In):
    endpoint: Annotated[str, StringConstraints(max_length=1000, pattern=r"^https://")]
    keys: PushKeys
    expirationTime: int | None = None  # noqa: N815 (formato do navegador)


class PushSubscribeIn(In):
    subscription: PushSubscriptionIn
    consent_marketing: Literal[True]


class PushUnsubscribeIn(In):
    endpoint: Annotated[str, StringConstraints(max_length=1000)]


class PushBroadcastIn(In):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    url: Annotated[str, StringConstraints(max_length=300, pattern=r"^/[^\s]*$")] | None = None


class PushBroadcastOut(BaseModel):
    targeted: int
    sent: int
    failed: int
    removed: int


class AuditOut(BaseModel):
    id: uuid.UUID
    actor_name: str | None
    actor_kind: str
    action: str
    target_type: str | None
    target_id: str | None
    details: dict
    created_at: datetime


MeOut.model_rebuild()
