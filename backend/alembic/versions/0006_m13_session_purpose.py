"""Separate survey and member chat sessions without copying historical inputs."""

import sqlalchemy as sa

from alembic import op

revision = "0006_m13"
down_revision = "0005_m10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "consultations",
        sa.Column("purpose", sa.String(16), nullable=False, server_default="SURVEY"),
    )
    op.create_check_constraint("purpose", "consultations", "purpose IN ('SURVEY', 'CHAT')")
    op.create_check_constraint(
        "chat_member", "consultations", "purpose <> 'CHAT' OR owner_user_id IS NOT NULL"
    )


def downgrade():
    op.drop_constraint(op.f("ck_consultations_chat_member"), "consultations", type_="check")
    op.drop_constraint(op.f("ck_consultations_purpose"), "consultations", type_="check")
    op.drop_column("consultations", "purpose")
