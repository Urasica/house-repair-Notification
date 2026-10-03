"""Keep payload-free request tombstones after explicit result deletion."""

from alembic import op

revision = "0003_m06"
down_revision = "0002_m05"
branch_labels = None
depends_on = None


def constraints(*, deleted: bool):
    op.drop_constraint(op.f("ck_request_runs_state"), "request_runs", type_="check")
    op.drop_constraint(op.f("ck_request_runs_state_payload"), "request_runs", type_="check")
    states = "'PROCESSING', 'COMPLETED', 'FAILED'" + (", 'DELETED'" if deleted else "")
    terminal = "'FAILED', 'DELETED'" if deleted else "'FAILED'"
    op.create_check_constraint(
        op.f("ck_request_runs_state"), "request_runs", f"state IN ({states})"
    )
    op.create_check_constraint(
        op.f("ck_request_runs_state_payload"),
        "request_runs",
        "(state = 'PROCESSING' AND finished_at IS NULL AND response_json IS NULL)"
        " OR (state = 'COMPLETED' AND finished_at IS NOT NULL AND response_json IS NOT NULL)"
        f" OR (state IN ({terminal}) AND finished_at IS NOT NULL AND response_json IS NULL)",
    )


def upgrade():
    constraints(deleted=True)


def downgrade():
    # Preserve payload-free refusal when the old schema cannot represent DELETED.
    op.execute("UPDATE request_runs SET state='FAILED' WHERE state='DELETED'")
    constraints(deleted=False)
