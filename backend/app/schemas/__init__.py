"""Contratos Pydantic de entrada e saída da API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.permissions import Role
from app.domain.states import RequestStatus, RequestType, TableStatus

Str80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Str120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
OptStr280 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)] | None
OptStr1000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
Username = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=32,
                                            pattern=r"^[a-z0-9._-]+$")]
Pin = Annotated[str, StringConstraints(pattern=r"^\d{4,8}$")]
HttpsUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500,
                                            pattern=r"^https://[^\s<>\"']+$")] | None


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- auth / users ----------
class LoginIn(In):
    username: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=32)]
    pin: str = Field(min_length=1, max_length=16)


class UserOut(Out):
    id: uuid.UUID
    name: str
    username: str
    role: Role
    active: bool


class MeOut(BaseModel):
    user: UserOut
    permissions: list[str]
    establishment: EstablishmentOut
    csrf_token: str


class EstablishmentOut(Out):
    id: uuid.UUID
    name: str
    timezone: str
    orders_enabled: bool


class EstablishmentPatch(In):
    name: Str120 | None = None
    timezone: Annotated[str, StringConstraints(max_length=64)] | None = None
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


class UserCreate(In):
    name: Str120
    username: Username
    role: Role
    pin: Pin


class UserPatch(In):
    name: Str120 | None = None
    role: Role | None = None
    active: bool | None = None
    pin: Pin | None = None


class ChangeOwnPin(In):
    current_pin: str = Field(min_length=1, max_length=16)
    new_pin: Pin


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
    opened_at: datetime
    opened_by_name: str


class TableOut(Out):
    id: uuid.UUID
    number: int
    name: str | None
    status: TableStatus
    active: bool
    public_url: str
    version: int
    session: SessionBrief | None = None
    pending_calls: int = 0
    pending_orders: int = 0
    bill_requested: bool = False


class PublicOpenIn(In):
    pin: str = Field(min_length=1, max_length=16, description="PIN de qualquer pessoa ativa da equipe")


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
    note: str | None
    total_cents: int
    items: list[OrderItemOut]


# ---------- service requests (chamados, pedidos e conta) ----------
class ServiceRequestOut(Out):
    id: uuid.UUID
    session_id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    table_name: str | None
    type: RequestType
    status: RequestStatus
    note: str | None
    order: OrderOut | None
    created_at: datetime
    completed_at: datetime | None
    completed_by_name: str | None
    version: int


class CustomerRequestIn(In):
    type: Literal["CHAMAR_ATENDENTE", "PEDIR_CONTA"]
    note: OptStr280 = None


# ---------- histórico da mesa ----------
class SessionDetailOut(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    table_name: str | None
    status: str
    opened_at: datetime
    opened_by_name: str
    closed_at: datetime | None
    closed_by_name: str | None
    requests: list[ServiceRequestOut]


class SessionHistoryOut(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    opened_at: datetime
    closed_at: datetime | None
    opened_by_name: str
    closed_by_name: str | None
    requests_count: int


class Page[T](BaseModel):
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
    orders_enabled: bool


class JoinOut(BaseModel):
    token: str
    expires_at: datetime


class CustomerSessionOut(BaseModel):
    session_id: uuid.UUID
    establishment_name: str
    timezone: str
    table_number: int
    table_name: str | None
    orders_enabled: bool
    opened_at: datetime
    requests: list[ServiceRequestOut]
    push_public_key: str | None


# ---------- avisos aos clientes ----------
class NoticeIn(In):
    title: Str120
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    active: bool = True
    send_push: bool = False


class NoticePatch(In):
    title: Str120 | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    active: bool | None = None


class NoticeOut(Out):
    id: uuid.UUID
    title: str
    message: str | None
    active: bool
    created_at: datetime


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


class PushBroadcastOut(BaseModel):
    targeted: int
    sent: int
    failed: int
    removed: int


class NoticeCreatedOut(BaseModel):
    notice: NoticeOut
    push: PushBroadcastOut | None = None


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
