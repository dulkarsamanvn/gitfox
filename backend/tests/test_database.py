from unittest.mock import patch

from pydantic import PostgresDsn
from sqlalchemy.exc import OperationalError

from app.db.database import Database


def test_plain_postgres_url_uses_installed_driver() -> None:
    database = Database(PostgresDsn("postgresql://gitfox:fake-password@localhost:5433/gitfox"))
    try:
        assert database.engine is not None
        assert database.engine.dialect.driver == "psycopg"
    finally:
        database.close()


def test_readiness_handles_database_connection_errors() -> None:
    database = Database(
        PostgresDsn("postgresql+psycopg://gitfox:fake-password@localhost:5433/gitfox")
    )
    try:
        assert database.engine is not None
        error = OperationalError("SELECT 1", {}, Exception("fake-password: connection refused"))
        with patch.object(database.engine, "connect", side_effect=error):
            assert database.is_ready() is False
    finally:
        database.close()
