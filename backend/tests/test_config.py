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
    assert (settings.max_review_files, settings.max_patch_chars, settings.max_file_patch_chars) == (
        10,
        20_000,
        10_000,
    )


def test_example_environment_is_valid() -> None:
    settings = Settings(_env_file=BACKEND_DIR / ".env.example")

    assert settings.app_name == "GitFox AI Code Reviewer"
    assert settings.database_url is not None
    assert settings.database_url.hosts()[0]["port"] == 5433
    assert len(settings.cors_origins) == 2
    assert settings.openai_api_key is None
    assert settings.github_token is None
    assert settings.max_review_files == 10
    assert settings.max_patch_chars == 20_000
    assert settings.max_file_patch_chars == 10_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_review_files", 0),
        ("max_review_files", 301),
        ("max_patch_chars", 0),
        ("max_patch_chars", 200_001),
        ("max_file_patch_chars", 0),
        ("max_file_patch_chars", 100_001),
        ("max_review_files", "invalid"),
    ],
)
def test_rejects_invalid_selection_limits(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_selection_limits_can_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_REVIEW_FILES", "3")
    monkeypatch.setenv("MAX_PATCH_CHARS", "8000")
    monkeypatch.setenv("MAX_FILE_PATCH_CHARS", "4000")
    settings = Settings(_env_file=None)
    assert (settings.max_review_files, settings.max_patch_chars, settings.max_file_patch_chars) == (
        3,
        8000,
        4000,
    )


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


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://gitfox:fake-password@localhost:5433/gitfox",
        "postgresql://gitfox:fake-password@host1:5433,host2:5433/gitfox",
    ],
)
def test_rejects_unsupported_database_connections(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


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
