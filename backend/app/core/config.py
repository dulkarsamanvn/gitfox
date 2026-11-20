"""Validated settings loaded from the environment and backend/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="GitFox AI Code Reviewer", min_length=1)
    cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    database_url: PostgresDsn | None = Field(default=None, repr=False)
    github_token: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    max_review_files: int = Field(default=10, ge=1, le=300)
    max_patch_chars: int = Field(default=20_000, ge=1, le=200_000)
    max_file_patch_chars: int = Field(default=10_000, ge=1, le=100_000)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, origins: list[AnyHttpUrl]) -> list[AnyHttpUrl]:
        for origin in origins:
            if (
                "*" in str(origin)
                or origin.username is not None
                or origin.password is not None
                or origin.path not in (None, "/")
                or origin.query is not None
                or origin.fragment is not None
            ):
                raise ValueError(
                    "CORS_ORIGINS must contain HTTP(S) origins without wildcards, "
                    "credentials, paths, queries, or fragments"
                )
        return origins

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: PostgresDsn | None) -> PostgresDsn | None:
        if value is not None:
            if value.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
                raise ValueError("DATABASE_URL must use PostgreSQL with the psycopg driver")
            if len(value.hosts()) != 1:
                raise ValueError("DATABASE_URL must specify a single database host")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
