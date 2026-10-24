"""Durable identity fences; old migrations and business history remain unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0018_identity_deletion_owner"
down_revision = "0017_human_application_clock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("identity_owner_command_authorizations",
                    sa.Column("authorization_id", sa.String(36), primary_key=True),
                    sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False))
    op.create_table("identity_legacy_issuer", sa.Column("singleton", sa.Integer, primary_key=True),
                    sa.Column("issuer", sa.Text, nullable=False),
                    sa.CheckConstraint("singleton = 1", name="ck_identity_issuer_singleton"))
    op.create_table("identity_fence_epoch", sa.Column("singleton", sa.Integer, primary_key=True),
                    sa.Column("revision", sa.BigInteger, nullable=False),
                    sa.CheckConstraint("singleton = 1 AND revision > 0", name="ck_identity_epoch_singleton"))
    op.execute("INSERT INTO identity_fence_epoch(singleton,revision) VALUES(1,1)")
    op.create_table("identity_deletion_operations",
                    sa.Column("operation_id", sa.String(36), primary_key=True),
                    sa.Column("issuer", sa.Text, nullable=False), sa.Column("subject", sa.String(64), nullable=False),
                    sa.Column("inventory_revision", sa.String(36), nullable=False),
                    sa.Column("request", sa.JSON, nullable=False), sa.Column("state", sa.String(16), nullable=False),
                    sa.Column("fence", sa.String(36), nullable=True),
                    sa.Column("revision", sa.BigInteger, nullable=False),
                    sa.Column("reference_count", sa.BigInteger, nullable=False),
                    sa.CheckConstraint("state IN ('frozen','released')", name="ck_identity_operation_state"),
                    sa.CheckConstraint("revision > 0 AND reference_count >= 0", name="ck_identity_operation_counts"),
                    sa.CheckConstraint("(state='frozen') = (fence IS NOT NULL)", name="ck_identity_operation_fence"))
    op.create_index("ix_identity_operation_target", "identity_deletion_operations", ["issuer", "subject"])
    op.create_index("identity_one_active_freeze", "identity_deletion_operations", ["issuer", "subject"],
                    unique=True, postgresql_where=sa.text("state='frozen'"), sqlite_where=sa.text("state='frozen'"))
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite supports schema/unit tests only; lifecycle effects refuse it.
    quoted = bind.dialect.identifier_preparer.quote_schema(bind.exec_driver_sql("SELECT current_schema()").scalar_one())
    op.execute("CREATE SEQUENCE identity_reference_revision MINVALUE 1")
    op.execute(f"""
        CREATE FUNCTION workflow_identity_owner_command_clock() RETURNS trigger LANGUAGE plpgsql
        SET search_path TO {quoted}, pg_catalog AS $$
        BEGIN
          IF (clock_timestamp() < NEW.valid_until) IS NOT TRUE THEN
            RAISE EXCEPTION 'identity_owner_command_authority_expired' USING ERRCODE='42501';
          END IF;
          RETURN NEW;
        END;$$;
        CREATE TRIGGER identity_owner_command_clock BEFORE INSERT ON identity_owner_command_authorizations
          FOR EACH ROW EXECUTE FUNCTION workflow_identity_owner_command_clock();
        CREATE CONSTRAINT TRIGGER identity_owner_command_commit AFTER INSERT ON identity_owner_command_authorizations
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION workflow_identity_owner_command_clock();
        CREATE FUNCTION workflow_identity_issuer_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'identity_mapping_immutable' USING ERRCODE='23514';END;$$;
        CREATE TRIGGER identity_legacy_issuer_immutable BEFORE UPDATE OR DELETE ON identity_legacy_issuer
          FOR EACH ROW EXECUTE FUNCTION workflow_identity_issuer_immutable();
        CREATE FUNCTION workflow_identity_write_lock() RETURNS trigger
        LANGUAGE plpgsql SET search_path TO {quoted}, pg_catalog AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock_shared(714402216003::bigint);
          PERFORM 1 FROM identity_fence_epoch WHERE singleton=1 FOR SHARE;
          IF NOT FOUND THEN RAISE EXCEPTION 'identity_fence_epoch_missing' USING ERRCODE='23514';END IF;
          PERFORM nextval('identity_reference_revision');
          RETURN NULL;
        END;$$;
        CREATE FUNCTION workflow_identity_refs(source text, document jsonb)
        RETURNS TABLE(issuer text,subject text) LANGUAGE plpgsql STABLE
        SET search_path TO {quoted}, pg_catalog AS $$
        BEGIN
          IF source='pm_namespace_ownership' THEN
            issuer:=document->>'authority_issuer';subject:=document->>'provisioner_subject';
          ELSIF source='resource_execution_contexts' THEN
            SELECT legacy.issuer INTO issuer FROM identity_legacy_issuer legacy WHERE singleton=1;
            subject:=document->>'created_by_subject';
          ELSE RAISE EXCEPTION 'identity_reference_source_unknown';
          END IF;
          IF NULLIF(btrim(subject),'') IS NULL OR NULLIF(btrim(issuer),'') IS NULL THEN issuer:=NULL;END IF;
          RETURN NEXT;
        END;$$;
        CREATE FUNCTION workflow_identity_row_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path TO {quoted}, pg_catalog AS $$
        BEGIN
          IF EXISTS(SELECT 1 FROM workflow_identity_refs(TG_TABLE_NAME,to_jsonb(NEW)) r
              JOIN identity_deletion_operations f ON f.state='frozen' AND f.issuer=r.issuer AND f.subject=r.subject)
            THEN RAISE EXCEPTION 'identity_reference_frozen' USING ERRCODE='23514';END IF;
          IF EXISTS(SELECT 1 FROM identity_deletion_operations WHERE state='frozen') AND
             EXISTS(SELECT 1 FROM workflow_identity_refs(TG_TABLE_NAME,to_jsonb(NEW)) WHERE issuer IS NULL)
            THEN RAISE EXCEPTION 'identity_legacy_issuer_unbound' USING ERRCODE='23514';END IF;
          RETURN NEW;
        END;$$;
    """)
    for table in ("pm_namespace_ownership", "resource_execution_contexts"):
        op.execute(f"CREATE TRIGGER identity_write_lock BEFORE INSERT OR UPDATE OR DELETE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION workflow_identity_write_lock()")
        op.execute(f"CREATE TRIGGER identity_row_guard BEFORE INSERT OR UPDATE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION workflow_identity_row_guard()")


def downgrade() -> None:
    raise RuntimeError("Identity lifecycle requires guarded cohort rollback; preserve fences and history")
