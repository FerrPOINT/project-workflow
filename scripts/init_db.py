#!/usr/bin/env python3
from __future__ import annotations

import sys

from sqlalchemy.exc import SQLAlchemyError

from project_workflow.config import get_settings
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    DatabaseUnavailable,
    ensure_migrated,
    get_engine,
    initialization_transaction,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

__doc__ = """Upgrade the database and bootstrap packaged catalogs once."""


def _configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _configure_output_encoding()
    try:
        settings = get_settings()
        engine = get_engine(settings.DATABASE_URL)
        with initialization_transaction(engine) as connection:
            ensure_migrated(connection)
            with SAUnitOfWork(connection) as uow:
                ensure_managed_catalog(uow)
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
