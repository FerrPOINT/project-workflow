"""Add opt-in single-task bindings without weakening legacy assignment predicates."""

import sqlalchemy as sa
from alembic import op

revision = "0015_single_task_assignments"
down_revision = "0014_launch_profile_only"
branch_labels = None
depends_on = None

# Frozen SQL: the prior predicates are retained verbatim from the real database.
_BINDING = (
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
_TECH = (
    "(workflow_key IS NOT NULL AND role_key IS NOT NULL AND "
    "role_key IN ('developer','reviewer','tester','devops') AND "
    "workflow_key = 'single-task-v1:' || role_key AND execution_scope = 'delivery' AND "
    "tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL)"
)


def upgrade() -> None:
    checks = {c["name"]: c["sqltext"] for c in
              sa.inspect(op.get_bind()).get_check_constraints("task_runtime_assignments")}
    names = {"ck_task_runtime_assignments_binding_complete": _BINDING,
             "ck_task_runtime_assignments_scope_tech_refs": _TECH}
    if not names.keys() <= checks.keys():
        raise RuntimeError("Expected predecessor assignment constraints are missing")
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.add_column(sa.Column("single_task_binding_json", sa.Text(), nullable=True))
        for name, branch in names.items():
            batch.drop_constraint(name, type_="check")
            legacy = f"({checks[name]})"
            if name.endswith("binding_complete"):
                legacy += " AND (workflow_key IS NULL OR workflow_key NOT LIKE 'single-task-v1:%')"
                legacy += " AND single_task_binding_json IS NULL"
            batch.create_check_constraint(name, f"{legacy} OR {branch}")
    with op.batch_alter_table("pm_executions") as batch:
        batch.drop_constraint("uq_pm_task_agent", type_="unique")
        batch.create_index("ix_pm_task_agent", ["tracker_instance_ref", "task_ref", "agent_ref"])


def downgrade() -> None:
    raise RuntimeError("Single-task binding/history must be preserved; restore a pre-migration backup")
