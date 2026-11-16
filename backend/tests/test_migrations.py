from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from alembic.util import CommandError

from app.core.config import BACKEND_DIR, Settings


def test_migration_generates_sql_without_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_settings_access() -> None:
        raise AssertionError("Offline SQL generation must not need database credentials")

    monkeypatch.setattr("app.core.config.get_settings", unexpected_settings_access)
    output = StringIO()
    config = Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=output)

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    for table in ("reviews", "findings", "review_files"):
        assert f"CREATE TABLE {table}" in sql
    assert "gen_random_uuid()" in sql
    assert "postgresql://" not in sql
    assert "postgresql+psycopg://" not in sql


def test_online_migration_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(_env_file=None))
    config = Config(str(BACKEND_DIR / "alembic.ini"))

    with pytest.raises(CommandError, match="Set DATABASE_URL"):
        command.current(config)
