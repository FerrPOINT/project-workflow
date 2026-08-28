#!/usr/bin/env python3
from __future__ import annotations

import sys

from sqlalchemy.exc import SQLAlchemyError

from project_workflow.config import get_settings
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    DatabaseUnavailable,
    ensure_migrated,
    get_engine,
    initialization_transaction,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

__doc__ = """Upgrade the database and bootstrap packaged catalogs once."""


def main() -> int:
    try:
        settings = get_settings()
        engine = get_engine(settings.DATABASE_URL)
        with initialization_transaction(engine) as connection:
            ensure_migrated(connection)
            with SAUnitOfWork(connection) as uow:
                schema.ensure_phase_catalog(uow)
                bootstrap_default_project(uow)
    except DatabaseRecreateRequired as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except DatabaseUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError):
        print("Не удалось инициализировать базу данных", file=sys.stderr)
        return 1
    protocol = settings.DATABASE_URL.split(":")[0]
    print(f"Alembic обновлён до head для {protocol}")

    print("Начальные каталоги загружены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
