from __future__ import annotations

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    ENV: str = "dev"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8010

    CORS_ORIGINS: str = "http://localhost:5174"

    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"  # lax|strict|none

    # Access token
    JWT_SECRET: str = "change_me"
    JWT_ALG: str = "HS256"
    ACCESS_EXPIRES_MINUTES: int = 15

    # Refresh token
    REFRESH_EXPIRES_DAYS: int = 14

    DATABASE_URL: str = "postgresql+psycopg://pm_agent_os_user:pm_agent_os_password@localhost:5434/pm_agent_os"

    # OpenAI chat (drafting)
    LLM_ENABLED: bool = False
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    OPENAI_TIMEOUT_SECONDS: int = 45

    # OpenAI embeddings (retrieval)
    EMBEDDINGS_MODEL: str = "text-embedding-3-small"
    EMBEDDINGS_DIM: int = 1536

    # Chunking
    CHUNK_SIZE_CHARS: int = 1100
    CHUNK_OVERLAP_CHARS: int = 150

    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()