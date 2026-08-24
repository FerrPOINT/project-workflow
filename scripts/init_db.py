#!/usr/bin/env python3
from __future__ import annotations

import sys

from project_workflow.config import get_settings
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    ensure_migrated,
    get_engine,
    initialization_transaction,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

__doc__ = """Upgrade the database and bootstrap packaged catalogs once."""


def main() -> int:
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    try:
        with initialization_transaction(engine) as connection:
            ensure_migrated(connection)
            uow = SAUnitOfWork(connection)
            schema.ensure_phase_catalog(uow)
            bootstrap_default_project(uow)
            uow.commit()
            uow.close()
    except DatabaseRecreateRequired as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    protocol = settings.DATABASE_URL.split(":")[0]
    print(f"Alembic upgraded to head for {protocol}")

    print("Initial catalogs ensured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
