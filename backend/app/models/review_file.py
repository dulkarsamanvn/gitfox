"""Per-file coverage metadata without retaining repository source code."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.review import Review


class ReviewFile(Base):
    __tablename__ = "review_files"
    __table_args__ = (
        UniqueConstraint("review_id", "path", name="uq_review_files_review_path"),
        CheckConstraint("additions >= 0 AND deletions >= 0", name="nonnegative_changes"),
        CheckConstraint("NOT reviewed OR skip_reason IS NULL", name="reviewed_without_skip_reason"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    review_id: Mapped[UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    additions: Mapped[int] = mapped_column(server_default=text("0"))
    deletions: Mapped[int] = mapped_column(server_default=text("0"))
    reviewed: Mapped[bool] = mapped_column(server_default=text("false"))
    skip_reason: Mapped[str | None] = mapped_column(Text)

    review: Mapped["Review"] = relationship(back_populates="files")
