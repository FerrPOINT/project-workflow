"""Give untouched built-in professions distinct initial presentation."""

import sqlalchemy as sa
from alembic import op

revision = "0012_profession_themes"
down_revision = "0011_profession_workflows"
branch_labels = None
depends_on = None

# Frozen migration values, independent of future runtime default changes.
_THEMES = {
    "project_manager": ("briefcase", "#F59E0B"),
    "analyst": ("chart", "#06B6D4"),
    "architect": ("layers", "#8B5CF6"),
    "developer": ("code", "#3B82F6"),
    "reviewer": ("shield", "#F97316"),
    "tester": ("flask", "#22C55E"),
    "devops": ("rocket", "#F43F5E"),
}


def upgrade() -> None:
    projects = sa.table(
        "projects", sa.column("workflow_id", sa.Integer), sa.column("cli_command", sa.String),
        sa.column("theme_icon", sa.String), sa.column("theme_color", sa.String),
    )
    workflows = sa.table("workflows", sa.column("id", sa.Integer), sa.column("key", sa.String))
    for role, (icon, color) in _THEMES.items():
        op.get_bind().execute(projects.update().where(
            projects.c.cli_command == f"workflow-{role}",
            projects.c.workflow_id.in_(sa.select(workflows.c.id).where(workflows.c.key == f"hermes-sdlc:{role}")),
            projects.c.theme_icon == "folder",
            sa.func.upper(projects.c.theme_color) == "#5E6AD2",
        ).values(theme_icon=icon, theme_color=color))


def downgrade() -> None:
    # Presentation only; retain choices rather than inventing earlier user edits.
    pass
