from typing import List, Literal, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    PROJECT_NAME: str = "ParcelPilot"
    API_V1_STR: str = "/api/v1"
    APP_ENV: Literal["development", "test", "production"] = "development"
    DEBUG: bool = True
    ALLOWED_ORIGINS: Union[List[str], str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    LOG_LEVEL: str = "INFO"
    REQUEST_TIMEOUT_SECONDS: int = 60
    BOOTSTRAP_DATA: bool = True
    DATA_DIR: str = "../data"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, str) and v.startswith("["):
            import json
            return json.loads(v)
        return v

    # PostgreSQL Database Settings
    POSTGRES_USER: str = "parcelpilot"
    POSTGRES_PASSWORD: str = "parcelpilot_secret"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "parcelpilot_db"
    DATABASE_URL: str = "postgresql+asyncpg://parcelpilot:parcelpilot_secret@localhost:5432/parcelpilot_db"

    # JWT Authentication & Security
    SECRET_KEY: str = "parcelpilot_dev_secret_key_change_me_in_production_123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # LLM & AI Agent Settings (LangChain / LangGraph)
    LLM_PROVIDER: str = "ollama"  # "ollama" or "openai"
    LLM_MODEL: str = "llama3"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OPENAI_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
