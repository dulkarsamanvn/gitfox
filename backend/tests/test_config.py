from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, Settings


def test_settings_boot_without_database_or_api_keys() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url is None
    assert settings.github_token is None
    assert settings.openai_api_key is None
    assert settings.openai_model is None


def test_example_environment_is_valid() -> None:
    settings = Settings(_env_file=BACKEND_DIR / ".env.example")

    assert settings.app_name == "GitFox AI Code Reviewer"
    assert settings.database_url is not None
    assert settings.database_url.hosts()[0]["port"] == 5433
    assert len(settings.cors_origins) == 2
    assert settings.openai_api_key is None
    assert settings.github_token is None


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'APP_NAME="File Name"\nCORS_ORIGINS=http://localhost:5173, https://example.com\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_NAME", "Environment Name")

    settings = Settings(_env_file=env_file)

    assert settings.app_name == "Environment Name"
    assert [str(origin).rstrip("/") for origin in settings.cors_origins] == [
        "http://localhost:5173",
        "https://example.com",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "ftp://example.com",
        "https://example.com/app",
        "https://user:password@example.com",
        "https://example.com?query=value",
        "https://example.com#fragment",
    ],
)
def test_rejects_invalid_browser_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=origin)


def test_rejects_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="https://example.com/database")


def test_credentials_are_hidden_from_settings_representation() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://gitfox:fake-db-password@localhost:5433/gitfox",
        github_token="fake-github-token",
        openai_api_key="fake-openai-key",
    )

    for credential in ("fake-db-password", "fake-github-token", "fake-openai-key"):
        assert credential not in repr(settings)


def test_validation_message_does_not_expose_input_credentials() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="https://gitfox:fake-password@example.com")

    assert "fake-password" not in str(error.value)
