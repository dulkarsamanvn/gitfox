"""Evidence and suggested actions produced by a review."""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Enum, ForeignKey, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.review import Review


class FindingSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(StrEnum):
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class FindingConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (CheckConstraint("line IS NULL OR line > 0", name="positive_line"),)

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    review_id: Mapped[UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(
            FindingSeverity,
            values_callable=lambda enum: [member.value for member in enum],
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="finding_severity",
            length=10,
        )
    )
    category: Mapped[FindingCategory] = mapped_column(
        Enum(
            FindingCategory,
            values_callable=lambda enum: [member.value for member in enum],
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="finding_category",
            length=30,
        )
    )
    file_path: Mapped[str] = mapped_column(Text)
    line: Mapped[int | None]
    title: Mapped[str] = mapped_column(String(200))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text)
    confidence: Mapped[FindingConfidence] = mapped_column(
        Enum(
            FindingConfidence,
            values_callable=lambda enum: [member.value for member in enum],
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name="finding_confidence",
            length=10,
        )
    )

    review: Mapped["Review"] = relationship(back_populates="findings")
