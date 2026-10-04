"""Protect published knowledge content while allowing explicit withdrawal.

Revision ID: 0004_m09
Revises: 0003_m06
"""

from alembic import op

revision = "0004_m09"
down_revision = "0003_m06"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION protect_knowledge_set() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status <> 'BUILDING' THEN
        IF TG_OP = 'UPDATE' AND OLD.status = 'PUBLISHED' AND NEW.status = 'WITHDRAWN'
           AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status') THEN
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Published knowledge set is immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_knowledge_set BEFORE UPDATE OR DELETE ON knowledge_sets
      FOR EACH ROW EXECUTE FUNCTION protect_knowledge_set();
    """)
    op.execute("""
    CREATE FUNCTION protect_knowledge_document() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE sid uuid; state text;
    BEGIN
      IF TG_OP = 'INSERT' THEN sid := NEW.knowledge_set_id;
      ELSE sid := OLD.knowledge_set_id; END IF;
      SELECT status INTO state FROM knowledge_sets WHERE id = sid FOR UPDATE;
      IF TG_OP = 'UPDATE' AND NEW.knowledge_set_id <> OLD.knowledge_set_id THEN
        RAISE EXCEPTION 'Cannot move knowledge documents';
      END IF;
      IF state <> 'BUILDING' THEN
        IF TG_OP = 'UPDATE' AND NEW.status = 'WITHDRAWN'
          AND (to_jsonb(NEW) - ARRAY['status','withdrawn_at','withdrawal_reason']) =
              (to_jsonb(OLD) - ARRAY['status','withdrawn_at','withdrawal_reason']) THEN
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Published knowledge document is immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_knowledge_document
      BEFORE INSERT OR UPDATE OR DELETE ON knowledge_documents
      FOR EACH ROW EXECUTE FUNCTION protect_knowledge_document();
    """)
    op.execute("""
    CREATE FUNCTION protect_knowledge_chunk() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE did uuid; state text;
    BEGIN
      IF TG_OP = 'INSERT' THEN did := NEW.document_id; ELSE did := OLD.document_id; END IF;
      SELECT s.status INTO state FROM knowledge_sets s JOIN knowledge_documents d
        ON d.knowledge_set_id = s.id WHERE d.id = did FOR UPDATE OF s;
      IF TG_OP = 'UPDATE' AND NEW.document_id <> OLD.document_id THEN
        RAISE EXCEPTION 'Cannot move knowledge chunks';
      END IF;
      IF state <> 'BUILDING' THEN RAISE EXCEPTION 'Published knowledge chunk is immutable'; END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER immutable_knowledge_chunk BEFORE INSERT OR UPDATE OR DELETE ON knowledge_chunks
      FOR EACH ROW EXECUTE FUNCTION protect_knowledge_chunk();
    """)


def downgrade():
    for table, name in (
        ("knowledge_chunks", "chunk"),
        ("knowledge_documents", "document"),
        ("knowledge_sets", "set"),
    ):
        op.execute(f"DROP TRIGGER immutable_knowledge_{name} ON {table}")
        op.execute(f"DROP FUNCTION protect_knowledge_{name}()")
