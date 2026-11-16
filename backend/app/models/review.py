"""Pull request review records and their coverage information."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, DateTime, Enum, Index, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.finding import Finding
    from app.models.review_file import ReviewFile


class ReviewStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("pr_number > 0", name="positive_pr_number"),
        CheckConstraint(
            "files_seen >= 0 AND files_reviewed >= 0 AND files_skipped >= 0",
            name="nonnegative_file_counts",
        ),
        CheckConstraint(
            "files_reviewed + files_skipped <= files_seen", name="coverage_within_seen"
        ),
        CheckConstraint("base_sha IS NULL OR base_sha ~ '^[0-9a-f]{40}$'", name="valid_base_sha"),
        CheckConstraint("head_sha IS NULL OR head_sha ~ '^[0-9a-f]{40}$'", name="valid_head_sha"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    pr_url: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(100))
    repository: Mapped[str] = mapped_column(String(100))
    pr_number: Mapped[int]
    title: Mapped[str | None] = mapped_column(Text)
    base_sha: Mapped[str | None] = mapped_column(CHAR(40))
    head_sha: Mapped[str | None] = mapped_column(CHAR(40))
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            values_callable=lambda enum: [member.value for member in enum],
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="review_status",
            length=16,
        ),
        server_default=ReviewStatus.PENDING.value,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    files_seen: Mapped[int] = mapped_column(server_default=text("0"))
    files_reviewed: Mapped[int] = mapped_column(server_default=text("0"))
    files_skipped: Mapped[int] = mapped_column(server_default=text("0"))
    model: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    findings: Mapped[list["Finding"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", passive_deletes=True
    )
    files: Mapped[list["ReviewFile"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", passive_deletes=True
    )


Index("ix_reviews_created_at_desc", Review.created_at.desc())
Index("ix_reviews_pr_head", Review.owner, Review.repository, Review.pr_number, Review.head_sha)
