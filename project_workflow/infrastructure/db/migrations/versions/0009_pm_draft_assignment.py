"""Allow initial PM Draft assignments without fabricating later-stage resources."""

from alembic import op

revision = "0009_pm_draft_assignment"
down_revision = "0008_pm_execution"
branch_labels = None
depends_on = None

# Frozen release expression. Historical assignment/migration bytes are preserved.
BINDING_COMPLETE = (
    '(workflow_key IS NULL AND role_key IS NULL AND execution_scope IS NULL AND stage_key IS NULL AND '
    'attempt_number IS NULL AND business_task_ref IS NULL AND root_task_ref IS NULL AND work_item_ref IS '
    'NULL AND work_item_revision IS NULL AND queue_item_ref IS NULL AND task_workspace_ref IS NULL AND '
    'workspace_revision IS NULL AND tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref '
    'IS NULL AND decomposition_revision_ref IS NULL AND stage_revision IS NULL AND assignment_ref IS NULL'
    ' AND binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND '
    'bind_request_sha256 IS NULL AND workspace_generation IS NULL AND lease_generation IS NULL AND '
    'exact_input_refs IS NULL AND payload_sha256 IS NULL) OR (workflow_key IS NOT NULL AND role_key IS '
    'NOT NULL AND execution_scope IS NOT NULL AND stage_key IS NOT NULL AND attempt_number IS NOT NULL '
    'AND business_task_ref IS NOT NULL AND root_task_ref IS NOT NULL AND work_item_ref IS NOT NULL AND '
    'work_item_revision IS NOT NULL AND queue_item_ref IS NOT NULL AND task_workspace_ref IS NOT NULL AND'
    ' workspace_revision IS NOT NULL AND decomposition_revision_ref IS NOT NULL AND stage_revision IS NOT'
    ' NULL AND assignment_ref IS NOT NULL AND workspace_generation IS NOT NULL AND lease_generation IS '
    'NOT NULL AND exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND ((binding_ref IS NULL '
    'AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND bind_request_sha256 IS NULL) OR '
    '(binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND ((bind_operation_key IS NULL AND '
    'bind_request_sha256 IS NULL) OR (bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT '
    "NULL))))) OR (workflow_key IS NOT NULL AND workflow_key = 'hermes-sdlc:project_manager' AND role_key"
    " IS NOT NULL AND role_key = 'project_manager' AND execution_scope IS NOT NULL AND execution_scope = "
    "'business' AND stage_key IS NOT NULL AND stage_key = 'draft' AND attempt_number IS NOT NULL AND "
    'attempt_number = 1 AND cycle_number = 0 AND business_task_ref IS NOT NULL AND root_task_ref IS NOT '
    'NULL AND work_item_ref IS NULL AND work_item_revision IS NULL AND queue_item_ref IS NULL AND '
    'task_workspace_ref IS NULL AND workspace_revision IS NULL AND workspace_generation IS NULL AND '
    'tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL AND '
    'decomposition_revision_ref IS NULL AND stage_revision IS NOT NULL AND assignment_ref IS NOT NULL AND'
    ' lease_generation IS NOT NULL AND exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND '
    '((binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND '
    'bind_request_sha256 IS NULL) OR (binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND '
    'bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL)))'
)


def upgrade() -> None:
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.drop_constraint("ck_task_runtime_assignments_binding_complete", type_="check")
        batch.create_check_constraint("ck_task_runtime_assignments_binding_complete", BINDING_COMPLETE)


def downgrade() -> None:
    raise RuntimeError("PM Draft assignment downgrade refused: immutable reservations require reconciliation")
