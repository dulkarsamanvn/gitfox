"""Exercise migrations and data integrity in disposable PostgreSQL schemas."""

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Connection,
    Engine,
    create_engine,
    delete,
    func,
    inspect,
    make_url,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, Settings
from app.db.database import Database
from app.models import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    Review,
    ReviewFile,
    ReviewStatus,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
    ),
]


def migration_config(connection: Connection) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def empty_engine() -> Iterator[Engine]:
    settings = Settings(_env_file=None, database_url=os.environ["TEST_DATABASE_URL"])
    database = Database(settings.database_url)
    assert database.engine is not None
    schema = "gitfox_test_" + uuid4().hex
    engine = None
    created = False
    try:
        with database.engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        url = make_url(str(settings.database_url)).set(drivername="postgresql+psycopg")
        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 3,
                "options": f"-c search_path={schema} -c statement_timeout=5000",
            },
            hide_parameters=True,
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            # Drop only this test's generated schema; application tables stay untouched.
            with database.engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        database.close()


@pytest.fixture
def migrated_engine(empty_engine: Engine) -> Engine:
    with empty_engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    return empty_engine


def test_migration_from_empty_schema_and_downgrade(empty_engine: Engine) -> None:
    with empty_engine.begin() as connection:
        assert inspect(connection).get_table_names() == []
        config = migration_config(connection)

        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == {
            "reviews",
            "findings",
            "review_files",
            "alembic_version",
        }
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        command.check(config)

        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        command.check(config)


def test_review_round_trip_and_database_cascade(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        review = Review(
            pr_url="https://github.com/example/project/pull/1",
            owner="example",
            repository="project",
            pr_number=1,
            base_sha="a" * 40,
            head_sha="b" * 40,
            files_seen=2,
            files_reviewed=1,
            files_skipped=1,
        )
        review.findings.append(
            Finding(
                severity=FindingSeverity.MEDIUM,
                category=FindingCategory.BUG,
                file_path="app.py",
                line=None,
                title="Possible missing guard",
                explanation="The collection may be empty.",
                evidence="The diff accesses values[0].",
                suggestion="Check that the collection is nonempty.",
                confidence=FindingConfidence.MEDIUM,
            )
        )
        review.files.extend(
            [
                ReviewFile(path="app.py", status="modified", reviewed=True, additions=2),
                ReviewFile(path="package-lock.json", status="modified", skip_reason="lock_file"),
            ]
        )
        session.add(review)
        session.commit()

        review_id = review.id
        assert isinstance(review_id, UUID)
        assert review.status == ReviewStatus.PENDING
        assert review.created_at.tzinfo is not None
        assert review.started_at is None
        assert review.completed_at is None
        assert isinstance(review.findings[0].id, UUID)

        session.expire_all()
        restored = session.get(Review, review_id)
        assert restored is not None
        assert restored.findings[0].category == FindingCategory.BUG
        assert restored.findings[0].line is None
        assert len(restored.files) == 2
        assert next(file for file in restored.files if not file.reviewed).skip_reason == "lock_file"

        # Bulk deletion bypasses ORM relationship cascades, exercising PostgreSQL's FK cascade.
        session.execute(delete(Review).where(Review.id == review_id))
        session.commit()
        assert session.scalar(select(func.count()).select_from(Finding)) == 0
        assert session.scalar(select(func.count()).select_from(ReviewFile)) == 0


@pytest.mark.parametrize(
    "invalid",
    [
        {"pr_number": 0},
        {"status": "unknown"},
        {"files_seen": -1},
        {"files_reviewed": -1},
        {"files_skipped": -1},
        {"files_seen": 1, "files_reviewed": 1, "files_skipped": 1},
        {"base_sha": "invalid-sha"},
        {"head_sha": "invalid-sha"},
    ],
)
def test_database_rejects_invalid_reviews(migrated_engine: Engine, invalid: dict) -> None:
    values = {
        "pr_url": "https://github.com/example/project/pull/1",
        "owner": "example",
        "repository": "project",
        "pr_number": 1,
        "status": "pending",
        "files_seen": 0,
        "files_reviewed": 0,
        "files_skipped": 0,
        "base_sha": None,
        "head_sha": None,
        **invalid,
    }
    # Raw SQL ensures PostgreSQL itself rejects invalid enum values and counters.
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reviews (pr_url, owner, repository, pr_number, status, "
                "files_seen, files_reviewed, files_skipped, base_sha, head_sha) "
                "VALUES (:pr_url, :owner, :repository, :pr_number, :status, "
                ":files_seen, :files_reviewed, :files_skipped, :base_sha, :head_sha)"
            ),
            values,
        )


def insert_review(connection: Connection) -> UUID:
    return connection.execute(
        text(
            "INSERT INTO reviews (pr_url, owner, repository, pr_number) "
            "VALUES ('https://github.com/example/project/pull/1', 'example', 'project', 1) "
            "RETURNING id"
        )
    ).scalar_one()


@pytest.mark.parametrize(
    "invalid",
    [
        {"severity": "fatal"},
        {"category": "style"},
        {"confidence": "certain"},
        {"line": 0},
        {"line": -1},
    ],
)
def test_database_rejects_invalid_findings(migrated_engine: Engine, invalid: dict) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        values = {
            "review_id": insert_review(connection),
            "severity": "medium",
            "category": "bug",
            "confidence": "medium",
            "line": 1,
            **invalid,
        }
        connection.execute(
            text(
                "INSERT INTO findings (review_id, severity, category, confidence, line, "
                "file_path, title, explanation, evidence, suggestion) "
                "VALUES (:review_id, :severity, :category, :confidence, :line, "
                "'app.py', 'Example', 'Explanation', 'Evidence', 'Suggestion')"
            ),
            values,
        )


@pytest.mark.parametrize(
    "invalid",
    [
        {"additions": -1},
        {"deletions": -1},
        {"reviewed": True, "skip_reason": "lock_file"},
    ],
)
def test_database_rejects_invalid_file_coverage(migrated_engine: Engine, invalid: dict) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        values = {
            "review_id": insert_review(connection),
            "additions": 0,
            "deletions": 0,
            "reviewed": False,
            "skip_reason": None,
            **invalid,
        }
        connection.execute(
            text(
                "INSERT INTO review_files (review_id, path, status, additions, deletions, "
                "reviewed, skip_reason) VALUES (:review_id, 'app.py', 'modified', :additions, "
                ":deletions, :reviewed, :skip_reason)"
            ),
            values,
        )


def test_database_rejects_duplicate_file_paths(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        review_id = insert_review(connection)
        statement = text(
            "INSERT INTO review_files (review_id, path, status) "
            "VALUES (:review_id, 'app.py', 'modified')"
        )
        connection.execute(statement, {"review_id": review_id})
        connection.execute(statement, {"review_id": review_id})
