from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração carregada de variáveis de ambiente (prefixo ANDRIPA_)."""

    model_config = SettingsConfigDict(env_prefix="ANDRIPA_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://atende:atende@localhost:5432/atende"
    redis_url: str = "redis://localhost:6379/0"

    # URL pública do frontend, usada para montar o link do QR Code / NFC.
    public_base_url: str = "http://localhost:5173"
    # Origens aceitas em CORS e no handshake de WebSocket.
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

    cookie_secure: bool = True
    staff_session_ttl_hours: int = 12
    staff_session_idle_minutes: int = 120
    customer_token_ttl_hours: int = 12

    max_body_bytes: int = 64 * 1024
    db_pool_size: int = 10
    db_null_pool: bool = False

    # Web Push (VAPID). Vazio = recurso desabilitado.
    vapid_public_key: str = ""
    vapid_private_key: str = ""  # PEM ou base64url do escalar privado P-256
    vapid_subject: str = "mailto:contato@example.com"

    outbox_poll_seconds: float = 0.5
    # Desligue para rodar o relay do outbox em um processo dedicado (ou em testes).
    relay_enabled: bool = True
    log_level: str = "INFO"

    # Diretório opcional com o build do frontend (single-container / e2e).
    frontend_dist_dir: str = ""

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
