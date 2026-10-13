"""Move execution configuration into professions and remove the agent registry."""

import sqlalchemy as sa
from alembic import op

revision = "0013_profession_execution"
down_revision = "0012_profession_themes"
branch_labels = None
depends_on = None


def _drop_assignment(table: str) -> None:
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    keys = sa.inspect(op.get_bind()).get_foreign_keys(table)
    with op.batch_alter_table(table, naming_convention=convention) as batch:
        for key in keys:
            if key["constrained_columns"] == ["agent_id"]:
                batch.drop_constraint(key["name"] or f"fk_{table}_agent_id_agents", type_="foreignkey")
        batch.drop_column("agent_id")


def upgrade() -> None:
    connection = op.get_bind()
    projects = sa.table("projects", sa.column("id", sa.Integer), sa.column("role_key", sa.String),
                        sa.column("launch_profile", sa.String), sa.column("execution_description", sa.Text))
    links = sa.table("profession_workflows", sa.column("profession_id", sa.Integer),
                     sa.column("workflow_id", sa.Integer))
    phases = sa.table("phases", sa.column("workflow_id", sa.Integer), sa.column("agent_id", sa.Integer))
    agents = sa.table("agents", sa.column("id", sa.Integer), sa.column("name", sa.String),
                      sa.column("hermes_profile", sa.String), sa.column("description", sa.Text))
    roles = sa.select(links.c.profession_id, sa.func.min(phases.c.agent_id).label("role_id")).join(
        phases, phases.c.workflow_id == links.c.workflow_id,
    ).group_by(links.c.profession_id).having(sa.func.count(sa.distinct(phases.c.agent_id)) == 1)
    assignments = list(connection.execute(roles))
    ambiguous = connection.execute(sa.select(links.c.profession_id).join(
        phases, phases.c.workflow_id == links.c.workflow_id,
    ).group_by(links.c.profession_id).having(sa.func.count(sa.distinct(phases.c.agent_id)) > 1)).scalars().all()
    unmapped = set(connection.execute(sa.select(agents.c.id)).scalars()) - {row.role_id for row in assignments}
    if ambiguous or unmapped:
        raise RuntimeError(
            f"Execution settings need a profession owner: ambiguous={ambiguous}, unmapped={sorted(unmapped)}"
        )
    op.add_column("projects", sa.Column("role_key", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("launch_profile", sa.String(251), nullable=True))
    op.add_column("projects", sa.Column("execution_description", sa.Text(), nullable=False, server_default=""))
    for profession_id, role_id in assignments:
        role = connection.execute(sa.select(agents).where(agents.c.id == role_id)).mappings().one()
        connection.execute(projects.update().where(projects.c.id == profession_id).values(
            role_key=role["name"], launch_profile=role["hermes_profile"],
            execution_description=role["description"] or "",
        ))
    op.add_column("pm_executions", sa.Column("role_key", sa.String(128), nullable=True))
    connection.execute(sa.text(
        "UPDATE pm_executions SET role_key = (SELECT name FROM agents WHERE id = pm_executions.agent_id)"
    ))
    _drop_assignment("phases")
    _drop_assignment("pm_executions")
    with op.batch_alter_table("pm_executions") as batch:
        batch.alter_column("role_key", existing_type=sa.String(128), nullable=False)
    op.drop_table("agents")


def downgrade() -> None:
    raise RuntimeError("The agent model was removed; restore the pre-migration backup to recover it")
