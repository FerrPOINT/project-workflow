"""Give professions workflow collections without changing saved task identities."""
import sqlalchemy as sa
from alembic import op

revision = "0011_profession_workflows"
down_revision = "0010_namespace_default_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    projects = sa.table("projects", sa.column("id", sa.Integer), sa.column("workflow_id", sa.Integer))
    pairs = connection.execute(sa.select(projects.c.id, projects.c.workflow_id)).all()
    membership = op.create_table(
        "profession_workflows",
        sa.Column("workflow_id", sa.Integer, sa.ForeignKey("workflows.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "profession_id", sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True,
        ),
    )
    op.create_index("ix_profession_workflows_profession_id", "profession_workflows", ["profession_id"])
    if pairs:
        # Existing shared templates remain shared; new UI workflows are created in one profession.
        connection.execute(membership.insert(), [
            {"workflow_id": workflow_id, "profession_id": profession_id}
            for profession_id, workflow_id in pairs
        ])


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(sa.text(
        "SELECT COUNT(*) FROM profession_workflows pw JOIN projects p ON p.id = pw.profession_id "
        "WHERE pw.workflow_id != p.workflow_id"
    )).scalar_one()
    if count:
        raise ValueError("Cannot downgrade profession collections with additional workflows; use a backed-up restore")
    op.drop_table("profession_workflows")
