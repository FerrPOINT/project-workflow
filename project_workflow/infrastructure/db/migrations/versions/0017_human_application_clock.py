"""Enforce the original application clock independently of space admission."""
from alembic import op

revision = "0017_human_application_clock"
down_revision = "0016_human_project_commit_guard"
branch_labels = None
depends_on = None

_TABLES = (
    'tasks',
    'task_runtime_assignments',
    'task_step_history',
    'task_phase_events',
    'resource_execution_contexts',
    'pm_executions',
    'pm_runs',
    'pm_operations',
    'pm_namespace_ownership',
    'workflows',
    'workflow_modes',
    'profession_workflows',
    'projects',
    'phases',
    'phase_instructions',
    'phase_checks',
    'phase_evidence_requirements',
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite is isolated test-only; ORM guards still check its flush/commit.
    schema = bind.exec_driver_sql("SELECT current_schema()").scalar_one()
    quoted = bind.dialect.identifier_preparer.quote_schema(schema)
    op.execute(f"""
        CREATE FUNCTION workflow_application_clock_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path TO {quoted}, pg_catalog AS $$
        DECLARE
          until_text text := nullif(current_setting('pdlc.workflow_request_until', true), '');
        BEGIN
          IF until_text IS NOT NULL AND
             (extract(epoch FROM clock_timestamp()) < until_text::double precision) IS NOT TRUE THEN
            RAISE EXCEPTION 'Original application admission expired' USING ERRCODE='42501';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$
    """)
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER workflow_application_write BEFORE INSERT OR UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION workflow_application_clock_guard()")
        op.execute(f"CREATE CONSTRAINT TRIGGER workflow_application_commit "
                   f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                   "WHEN (nullif(current_setting('pdlc.workflow_request_until', true), '') IS NOT NULL) "
                   "EXECUTE FUNCTION workflow_application_clock_guard()")


def downgrade() -> None:
    raise RuntimeError("Application policy requires a compatible guarded rollback cohort")
