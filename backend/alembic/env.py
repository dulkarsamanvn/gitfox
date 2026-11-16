"""Run migrations using the application's settings and model metadata."""

from logging.config import fileConfig

from alembic import context
from alembic.util import CommandError
from sqlalchemy import Connection, create_engine, make_url
from sqlalchemy.pool import NullPool

from app import models
from app.core.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    # SQL generation does not need a connection or database credentials.
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # An explicit connection lets integration tests migrate an isolated schema.
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate_connection(connection)
        return

    settings = get_settings()
    if settings.database_url is None:
        raise CommandError("Set DATABASE_URL in backend/.env before running migrations.")
    url = make_url(str(settings.database_url)).set(drivername="postgresql+psycopg")
    engine = create_engine(
        url, poolclass=NullPool, connect_args={"connect_timeout": 5}, hide_parameters=True
    )
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
