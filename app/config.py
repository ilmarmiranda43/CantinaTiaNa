from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "sim"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Cantina Escolar")
    environment: str = os.getenv("ENVIRONMENT", "development").lower()
    secret_key: str = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./cantina.db")
    admin_email: str = os.getenv("ADMIN_EMAIL", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    admin_name: str = os.getenv("ADMIN_NAME", "Administrador")
    whatsapp_service_url: str = os.getenv("WHATSAPP_SERVICE_URL", "http://localhost:3001")
    whatsapp_api_key: str = os.getenv("WHATSAPP_API_KEY", "")
    whatsapp_session_id: str = os.getenv("WHATSAPP_SESSION_ID", "cantina-principal")
    whatsapp_timeout_seconds: float = float(os.getenv("WHATSAPP_TIMEOUT_SECONDS", "15"))
    force_https_cookie: bool = _bool("FORCE_HTTPS_COOKIE", False)

    @property
    def sqlalchemy_url(self) -> str:
        value = self.database_url
        if value.startswith("postgres://"):
            value = "postgresql+psycopg://" + value[len("postgres://") :]
        elif value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

