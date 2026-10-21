"""Guard human writes after SQL row waits and at deferred commit; preserve native protocols."""

from alembic import op

revision = "0016_human_project_commit_guard"
down_revision = "0015_single_task_assignments"
branch_labels = None
depends_on = None

# These are the existing owner-bearing rows and shared execution definitions.
_TABLES = (
    "tasks", "task_runtime_assignments", "task_step_history", "task_phase_events",
    "resource_execution_contexts", "pm_executions", "pm_runs", "pm_operations", "pm_namespace_ownership",
    "workflows", "workflow_modes", "profession_workflows", "projects", "phases",
    "phase_instructions", "phase_checks", "phase_evidence_requirements",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite retains the application guards; PostgreSQL is the runtime boundary.
    schema = bind.exec_driver_sql("SELECT current_schema()").scalar_one()
    quoted = bind.dialect.identifier_preparer.quote_schema(schema)
    op.execute(f"""
        CREATE FUNCTION workflow_human_assert(owner_table text, resource jsonb)
        RETURNS void LANGUAGE plpgsql SET search_path TO {quoted}, pg_catalog AS $$
        DECLARE
          permit jsonb := nullif(current_setting('pdlc.workflow_human', true), '')::jsonb;
          task_owner bigint;
          binding record;
          namespace jsonb;
        BEGIN
          IF permit IS NULL THEN RETURN; END IF;
          IF (permit->>'product_role') NOT IN ('admin','platform_admin','operator','platform_operator')
             OR (permit->>'product_role') IS NULL THEN
            RAISE EXCEPTION 'Confirmed Workflow operator role required' USING ERRCODE='42501';
          END IF;
          IF (extract(epoch FROM clock_timestamp()) < (permit->>'deadline')::double precision) IS NOT TRUE THEN
            RAISE EXCEPTION 'Original project admission expired' USING ERRCODE='42501';
          END IF;
          IF owner_table IN ('pm_executions','pm_runs','pm_operations','pm_namespace_ownership') THEN
            RAISE EXCEPTION 'Native execution protocol required' USING ERRCODE='42501';
          END IF;
          IF owner_table='resource_execution_contexts' THEN
            namespace := resource->'request'->'context'->'namespace';
            IF ((permit->'writable_project_ids') ? (resource->'verified_projection'->>'tracker_project_id')
                AND resource->'request'->'context'->'task'->>'tracker_instance_id'
                    = permit->>'canonical_tracker_instance_id'
                AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(permit->'writable_spaces') s
                    WHERE s->>'registry_instance_id'=namespace->>'registry_instance_id'
                      AND s->>'space_id'=namespace->>'namespace_id'
                )) IS NOT TRUE THEN
              RAISE EXCEPTION 'Context owner space denied' USING ERRCODE='42501';
            END IF;
          ELSIF owner_table IN ('tasks','task_runtime_assignments','task_step_history','task_phase_events') THEN
            task_owner := (CASE WHEN owner_table='tasks' THEN resource->>'id' ELSE resource->>'task_id' END)::bigint;
            -- Hold the exact binding through commit; a profession is never a project owner.
            SELECT tracker_instance_ref,tracker_project_ref INTO binding
              FROM pm_executions WHERE task_id=task_owner FOR SHARE;
            IF NOT FOUND OR (binding.tracker_instance_ref = permit->>'tracker_instance_id'
                 AND (permit->'writable_project_ids') ? binding.tracker_project_ref) IS NOT TRUE THEN
              RAISE EXCEPTION 'Current project owner mapping required' USING ERRCODE='42501';
            END IF;
          END IF;
          -- The mapping lock itself may have waited past the original permit.
          IF (extract(epoch FROM clock_timestamp()) < (permit->>'deadline')::double precision) IS NOT TRUE THEN
            RAISE EXCEPTION 'Original project admission expired' USING ERRCODE='42501';
          END IF;
        END;
        $$
    """)
    op.execute(f"""
        CREATE FUNCTION workflow_human_row_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path TO {quoted}, pg_catalog AS $$
        BEGIN
          IF TG_OP <> 'INSERT' THEN PERFORM workflow_human_assert(TG_TABLE_NAME,to_jsonb(OLD)); END IF;
          IF TG_OP <> 'DELETE' THEN PERFORM workflow_human_assert(TG_TABLE_NAME,to_jsonb(NEW)); END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$
    """)
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER workflow_human_write BEFORE INSERT OR UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION workflow_human_row_guard()")
        # Native catalog work must not queue no-op deferred events: PostgreSQL
        # rejects subsequent DDL while such events remain pending in the transaction.
        op.execute(f"CREATE CONSTRAINT TRIGGER workflow_human_commit AFTER INSERT OR UPDATE OR DELETE ON {table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                   "WHEN (nullif(current_setting('pdlc.workflow_human', true), '') IS NOT NULL) "
                   "EXECUTE FUNCTION workflow_human_row_guard()")


def downgrade() -> None:
    raise RuntimeError("Human policy requires a compatible guarded rollback cohort")
