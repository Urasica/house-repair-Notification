"""Persist bounded chat reservations independently of deletable conversations.

Revision ID: 0005_m10
Revises: 0004_m09
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_m10"
down_revision = "0004_m09"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_usage",
        sa.Column("owner_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chat_usage_owner_created", "chat_usage", ["owner_user_id", "created_at"])


def downgrade():
    op.drop_table("chat_usage")
