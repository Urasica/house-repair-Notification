"""Protect published catalogs without changing the original M03 migration."""

from alembic import op

revision = "0002_m05"
down_revision = "0001_m03"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION guard_published_catalog() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'PUBLISHED' THEN
                RAISE EXCEPTION 'Published catalogs are immutable' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER catalogs_published_immutable BEFORE UPDATE OR DELETE ON catalogs
        FOR EACH ROW EXECUTE FUNCTION guard_published_catalog()
    """)


def downgrade():
    op.execute("DROP TRIGGER catalogs_published_immutable ON catalogs")
    op.execute("DROP FUNCTION guard_published_catalog()")
