from __future__ import annotations

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    # Environment
    ENV: str = "dev"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8010

    # CORS
    CORS_ORIGINS: str = "http://localhost:5174"

    # Cookies
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"  # lax|strict|none

    # JWT
    JWT_SECRET: str = "change_me"
    JWT_ALG: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 60

    # Database
    DATABASE_URL: str = "postgresql+psycopg://pm_agent_os_user:pm_agent_os_password@localhost:5434/pm_agent_os"

    # OpenAI / LLM
    LLM_ENABLED: bool = False
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    OPENAI_TIMEOUT_SECONDS: int = 45

    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()