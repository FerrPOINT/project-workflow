"""Narrow SQL branches for current metadata; migrations freeze their copy."""

SINGLE_TASK_BINDING = (
    "(workflow_key IS NOT NULL AND role_key IS NOT NULL AND "
    "role_key IN ('project_manager','analyst','architect','developer','reviewer','tester','devops') AND "
    "workflow_key = 'single-task-v1:' || role_key AND execution_scope IS NOT NULL AND "
    "execution_scope IN ('business','delivery') AND "
    "stage_key IS NOT NULL AND attempt_number IS NOT NULL AND business_task_ref IS NOT NULL AND "
    "root_task_ref IS NOT NULL AND business_task_ref = root_task_ref AND assignment_ref IS NOT NULL AND "
    "work_item_ref IS NULL AND work_item_revision IS NULL AND queue_item_ref IS NULL AND "
    "task_workspace_ref IS NULL AND workspace_revision IS NULL AND workspace_generation IS NULL AND "
    "decomposition_revision_ref IS NULL AND stage_revision IS NULL AND lease_generation IS NULL AND "
    "exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL AND "
    "((binding_ref IS NULL AND hermes_run_ref IS NULL AND bind_operation_key IS NULL AND "
    "bind_request_sha256 IS NULL AND single_task_binding_json IS NULL) OR "
    "(binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND bind_operation_key IS NOT NULL AND "
    "bind_request_sha256 IS NOT NULL AND concrete_agent_ref IS NOT NULL AND single_task_binding_json IS NOT NULL)))"
)
SINGLE_TASK_TECH = (
    "(workflow_key IS NOT NULL AND role_key IS NOT NULL AND "
    "role_key IN ('developer','reviewer','tester','devops') AND "
    "workflow_key = 'single-task-v1:' || role_key AND execution_scope = 'delivery' AND "
    "tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL)"
)
