"""Persist survey embedding reservations across session deletion and restarts.

Revision ID: 0007_survey_usage
Revises: 0006_m13
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_survey_usage"
down_revision = "0006_m13"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "survey_usage",
        sa.Column("session_key", sa.String(64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_survey_usage_session_created", "survey_usage", ["session_key", "created_at"]
    )
    op.create_index("ix_survey_usage_created", "survey_usage", ["created_at"])


def downgrade():
    op.drop_table("survey_usage")
