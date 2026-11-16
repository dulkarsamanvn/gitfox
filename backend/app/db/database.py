"""A shared SQLAlchemy connection pool for PostgreSQL."""

from pydantic import PostgresDsn
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import SQLAlchemyError


class Database:
    def __init__(self, database_url: PostgresDsn | None) -> None:
        self.engine: Engine | None = None
        if database_url is not None:
            # Use the installed psycopg driver for plain PostgreSQL URLs too.
            url = make_url(str(database_url)).set(drivername="postgresql+psycopg")
            self.engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=0,
                pool_timeout=3,
                connect_args={
                    "connect_timeout": 3,
                    "options": "-c statement_timeout=3000",
                },
                hide_parameters=True,
            )

    def is_ready(self) -> bool:
        """Check an authenticated connection without exposing driver errors."""
        if self.engine is None:
            return False
        try:
            with self.engine.connect() as connection:
                return connection.execute(text("SELECT 1")).scalar_one() == 1
        except SQLAlchemyError:
            return False

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
