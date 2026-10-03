"""Immutable v1 SQL for migration 0008 and its ORM counterpart; version future changes."""

ASSIGNMENT_SHAPE_V1_SQL = "assignment_shape IS NULL OR assignment_shape = 'business-pre-decomposition'"

_LEGACY_BINDING_V1_SQL = (
    "(workflow_key IS NULL AND role_key IS NULL AND execution_scope IS NULL AND stage_key IS NULL AND "
    "attempt_number IS NULL AND business_task_ref IS NULL AND root_task_ref IS NULL AND "
    "work_item_ref IS NULL AND work_item_revision IS NULL AND queue_item_ref IS NULL AND "
    "task_workspace_ref IS NULL AND workspace_revision IS NULL AND "
    "tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL AND "
    "decomposition_revision_ref IS NULL AND stage_revision IS NULL AND assignment_ref IS NULL AND "
    "binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
    "bind_request_sha256 IS NULL AND workspace_generation IS NULL AND "
    "lease_generation IS NULL AND exact_input_refs IS NULL AND payload_sha256 IS NULL) OR "
    "(workflow_key IS NOT NULL AND role_key IS NOT NULL AND execution_scope IS NOT NULL AND "
    "stage_key IS NOT NULL AND attempt_number IS NOT NULL AND business_task_ref IS NOT NULL AND "
    "root_task_ref IS NOT NULL AND work_item_ref IS NOT NULL AND work_item_revision IS NOT NULL AND "
    "queue_item_ref IS NOT NULL AND task_workspace_ref IS NOT NULL AND workspace_revision IS NOT NULL AND "
    "decomposition_revision_ref IS NOT NULL AND stage_revision IS NOT NULL AND assignment_ref IS NOT NULL AND "
    "workspace_generation IS NOT NULL AND lease_generation IS NOT NULL AND "
    "exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND "
    "((binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
    "bind_request_sha256 IS NULL) OR (binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND "
    "((bind_operation_key IS NULL AND bind_request_sha256 IS NULL) OR "
    "(bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL)))))"
)

_PRE_DECOMPOSITION_V1_SQL = (
    "assignment_shape IS NOT NULL AND assignment_shape = 'business-pre-decomposition' AND "
    "workflow_key IS NOT NULL AND role_key IS NOT NULL AND execution_scope IS NOT NULL AND "
    "workflow_key = 'hermes-sdlc:' || role_key AND "
    "role_key IN ('project_manager', 'analyst', 'architect') AND execution_scope = 'business' AND "
    "stage_key IS NOT NULL AND attempt_number IS NOT NULL AND business_task_ref IS NOT NULL AND "
    "root_task_ref IS NOT NULL AND work_item_ref IS NOT NULL AND work_item_revision IS NOT NULL AND "
    "queue_item_ref IS NOT NULL AND stage_revision IS NOT NULL AND assignment_ref IS NOT NULL AND "
    "exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND "
    "decomposition_revision_ref IS NULL AND tech_execution_workspace_ref IS NULL AND "
    "tech_execution_attempt_ref IS NULL AND workspace_generation IS NULL AND lease_generation IS NULL AND "
    "((task_workspace_ref IS NULL AND workspace_revision IS NULL) OR "
    "(task_workspace_ref IS NOT NULL AND length(trim(task_workspace_ref)) BETWEEN 1 AND 512 AND "
    "workspace_revision IS NOT NULL AND workspace_revision > 0)) AND "
    "((binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
    "bind_request_sha256 IS NULL) OR (binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND "
    "((bind_operation_key IS NULL AND bind_request_sha256 IS NULL) OR "
    "(bind_operation_key IS NOT NULL AND bind_request_sha256 IS NOT NULL))))"
)

PRE_DECOMPOSITION_BINDING_V1_SQL = (
    f"(assignment_shape IS NULL AND ({_LEGACY_BINDING_V1_SQL})) OR ({_PRE_DECOMPOSITION_V1_SQL})"
)
