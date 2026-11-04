"""Contratos Pydantic de entrada e saída da API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.permissions import Role
from app.domain.states import RequestStatus, RequestType, TableStatus, TagStatus

Str80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Str120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
OptStr280 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)] | None
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254,
                                         pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


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


class EstablishmentPatch(In):
    name: Str120 | None = None
    timezone: Annotated[str, StringConstraints(max_length=64)] | None = None
    join_code_required: bool | None = None

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


class TagBrief(Out):
    id: uuid.UUID
    status: TagStatus
    uid: str | None = None
    error: str | None = None
    updated_at: datetime


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
    tag: TagBrief | None = None


class OpenTableIn(In):
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    confirm_secret: str = Field(min_length=4, max_length=256, description="PIN pessoal ou senha")


class CloseSessionIn(In):
    expected_version: int | None = Field(default=None, description="Versão da sessão vista pelo painel (evita fechar às cegas)")


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


# ---------- detalhe e histórico de sessões ----------
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
    opened_at: datetime
    requests: list[ServiceRequestOut]


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


# ---------- etiquetas NFC (provisionamento) ----------
class ProvisionIn(In):
    number: int = Field(ge=1, le=9999)
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    confirm_secret: str = Field(min_length=4, max_length=256, description="PIN pessoal ou senha do administrador")


class TagStartIn(In):
    confirm_secret: str = Field(min_length=4, max_length=256)
    replace: bool = False


class TagWrittenIn(In):
    uid: str = Field(min_length=8, max_length=40, pattern=r"^[0-9A-Fa-f:]+$")
    read_url: str = Field(min_length=1, max_length=500, description="URL lida de volta da etiqueta")


class TagFailedIn(In):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]


class TagLockAuthIn(In):
    confirm_secret: str = Field(min_length=4, max_length=256)


class TagOut(Out):
    id: uuid.UUID
    table_id: uuid.UUID
    table_number: int
    table_name: str | None
    status: TagStatus
    url: str
    uid: str | None
    error: str | None
    started_by_name: str
    lock_authorized_at: datetime | None
    written_at: datetime | None
    locked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class ProvisionOut(BaseModel):
    table: TableOut
    tag: TagOut
    qr_svg_url: str


# ---------- planta do salão ----------
GRID_COLS = 24
GRID_ROWS = 16


class LayoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    table_id: uuid.UUID
    x: int = Field(ge=0, lt=GRID_COLS)
    y: int = Field(ge=0, lt=GRID_ROWS)


class LayoutOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    version: int
    cols: int = GRID_COLS
    rows: int = GRID_ROWS
    items: list[LayoutItem]
    updated_at: datetime


class LayoutCreateIn(In):
    name: Str80
    copy_from: uuid.UUID | None = None


class LayoutRenameIn(In):
    name: Str80


class LayoutItemsIn(In):
    version: int = Field(ge=1)
    items: list[LayoutItem] = Field(max_length=GRID_COLS * GRID_ROWS)
