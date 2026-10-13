"""Keep only the launch profile in profession execution settings."""

from alembic import op

revision = "0014_launch_profile_only"
down_revision = "0013_profession_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("role_key")
        batch.drop_column("execution_description")
    with op.batch_alter_table("pm_executions") as batch:
        batch.drop_column("role_key")


def downgrade() -> None:
    raise RuntimeError("Removed duplicate configuration; restore the pre-migration backup")
