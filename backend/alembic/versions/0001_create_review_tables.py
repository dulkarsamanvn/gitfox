"""create review tables

Revision ID: 0001
Revises: none
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pr_url", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("repository", sa.String(length=100), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("base_sha", sa.CHAR(length=40), nullable=True),
        sa.Column("head_sha", sa.CHAR(length=40), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                name="review_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("files_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("files_reviewed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("files_skipped", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "base_sha IS NULL OR base_sha ~ '^[0-9a-f]{40}$'",
            name=op.f("ck_reviews_valid_base_sha"),
        ),
        sa.CheckConstraint(
            "head_sha IS NULL OR head_sha ~ '^[0-9a-f]{40}$'",
            name=op.f("ck_reviews_valid_head_sha"),
        ),
        sa.CheckConstraint(
            "files_reviewed + files_skipped <= files_seen",
            name=op.f("ck_reviews_coverage_within_seen"),
        ),
        sa.CheckConstraint(
            "files_seen >= 0 AND files_reviewed >= 0 AND files_skipped >= 0",
            name=op.f("ck_reviews_nonnegative_file_counts"),
        ),
        sa.CheckConstraint("pr_number > 0", name=op.f("ck_reviews_positive_pr_number")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index(
        "ix_reviews_created_at_desc",
        "reviews",
        [sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_reviews_pr_head",
        "reviews",
        ["owner", "repository", "pr_number", "head_sha"],
        unique=False,
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "critical",
                "high",
                "medium",
                "low",
                "info",
                name="finding_severity",
                native_enum=False,
                create_constraint=True,
                length=10,
            ),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "bug",
                "security",
                "performance",
                "maintainability",
                name="finding_category",
                native_enum=False,
                create_constraint=True,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column(
            "confidence",
            sa.Enum(
                "high",
                "medium",
                "low",
                name="finding_confidence",
                native_enum=False,
                create_constraint=True,
                length=10,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("line IS NULL OR line > 0", name=op.f("ck_findings_positive_line")),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_findings_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index(op.f("ix_findings_review_id"), "findings", ["review_id"], unique=False)
    op.create_table(
        "review_files",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("additions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deletions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reviewed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "NOT reviewed OR skip_reason IS NULL",
            name=op.f("ck_review_files_reviewed_without_skip_reason"),
        ),
        sa.CheckConstraint(
            "additions >= 0 AND deletions >= 0", name=op.f("ck_review_files_nonnegative_changes")
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            name=op.f("fk_review_files_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_files")),
        sa.UniqueConstraint("review_id", "path", name="uq_review_files_review_path"),
    )


def downgrade() -> None:
    op.drop_table("review_files")
    op.drop_index(op.f("ix_findings_review_id"), table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_reviews_pr_head", table_name="reviews")
    op.drop_index("ix_reviews_created_at_desc", table_name="reviews")
    op.drop_table("reviews")
