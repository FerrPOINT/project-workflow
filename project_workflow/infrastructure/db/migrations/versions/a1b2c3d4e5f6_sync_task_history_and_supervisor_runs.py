"""sync task_history / supervisor_runs columns with ORM models

Model changes in review/full-audit (45e4650, 62fc5d3) were not accompanied
by Alembic revisions, so create_all-based SQLite tests stayed green while
existing PostgreSQL databases never received them:

1. task_history.phase_id: drop the phases.id FK. The column may store phase
   codes/sentinels per the app convention shared with tasks.current_phase
   (see becf90549ae1); nothing should enforce an FK here.
2. supervisor_runs.phase_id: make nullable. Assessments referencing phase
   codes not present in phases persist NULL there (code preserved in
   context_snapshot).

Revision ID: a1b2c3d4e5f6
Revises: becf90549ae1
Create Date: 2026-08-20 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "becf90549ae1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # SQLite cannot drop FKs in place; task_history inserts always pass
        # int ids (uow.add_task_history coerces), so the FK is harmless there.
        conn.execute(text("SELECT 1"))
        return

    # 1. task_history.phase_id: drop FK (column keeps Integer type).
    conn.execute(text("ALTER TABLE task_history DROP CONSTRAINT IF EXISTS task_history_phase_id_fkey"))

    # 2. supervisor_runs.phase_id: nullable for unresolved phase codes.
    conn.execute(text("ALTER TABLE supervisor_runs DROP CONSTRAINT IF EXISTS supervisor_runs_phase_id_fkey"))
    conn.execute(text("ALTER TABLE supervisor_runs ALTER COLUMN phase_id DROP NOT NULL"))
    conn.execute(
        text("ALTER TABLE supervisor_runs ADD CONSTRAINT supervisor_runs_phase_id_fkey "
             "FOREIGN KEY (phase_id) REFERENCES phases (id)")
    )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        conn.execute(text("SELECT 1"))
        return

    conn.execute(text("ALTER TABLE supervisor_runs DROP CONSTRAINT IF EXISTS supervisor_runs_phase_id_fkey"))
    conn.execute(text("ALTER TABLE supervisor_runs ALTER COLUMN phase_id SET NOT NULL"))
    conn.execute(
        text("ALTER TABLE supervisor_runs ADD CONSTRAINT supervisor_runs_phase_id_fkey "
             "FOREIGN KEY (phase_id) REFERENCES phases (id)")
    )
    conn.execute(text("ALTER TABLE task_history ADD CONSTRAINT task_history_phase_id_fkey "
                      "FOREIGN KEY (phase_id) REFERENCES phases (id)"))
