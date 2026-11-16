"""Import all models so their tables are registered for Alembic."""

from app.db.base import Base
from app.models.finding import Finding, FindingCategory, FindingConfidence, FindingSeverity
from app.models.review import Review, ReviewStatus
from app.models.review_file import ReviewFile

__all__ = [
    "Base",
    "Finding",
    "FindingCategory",
    "FindingConfidence",
    "FindingSeverity",
    "Review",
    "ReviewFile",
    "ReviewStatus",
]
