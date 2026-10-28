"""Separate saved task identities from the profession's legacy default workflow."""

import sqlalchemy as sa
from alembic import op

revision = "0021_profession_task_workflows"
down_revision = "0020_configured_cli_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_project_workflow", type_="foreignkey")
        batch.create_foreign_key("fk_tasks_project", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.drop_constraint("fk_task_runtime_assignments_project_workflow", type_="foreignkey")


def downgrade() -> None:
    for table in ("tasks", "task_runtime_assignments"):
        if op.get_bind().execute(sa.text(
            f"SELECT 1 FROM {table} t JOIN projects p ON p.id=t.project_id "
            "WHERE t.workflow_id != p.workflow_id LIMIT 1"
        )).first():
            raise RuntimeError("Additional profession workflow history prevents downgrade; preserve the database")
    with op.batch_alter_table("task_runtime_assignments") as batch:
        batch.create_foreign_key("fk_task_runtime_assignments_project_workflow", "projects",
                                 ["project_id", "workflow_id"], ["id", "workflow_id"], ondelete="RESTRICT")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_project", type_="foreignkey")
        batch.create_foreign_key("fk_tasks_project_workflow", "projects",
                                 ["project_id", "workflow_id"], ["id", "workflow_id"], ondelete="RESTRICT")
