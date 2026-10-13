#!/usr/bin/env python3
from __future__ import annotations

import sys

from sqlalchemy.exc import SQLAlchemyError

from project_workflow import config
from project_workflow.config import get_settings
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog, load_managed_catalog
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
    readback = None
    try:
        settings = get_settings()
        engine = get_engine(settings.DATABASE_URL)
        with initialization_transaction(engine) as connection:
            ensure_migrated(connection)
            with SAUnitOfWork(connection) as uow:
                uow.lock_catalog_state()
                if config.CATALOG_VARIANT == "single-task-v1":
                    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

                    readback = ensure_single_task_catalog(uow)
                else:
                    catalog = load_managed_catalog()
                    managed_keys = {workflow.key for workflow in catalog.workflows}
                    installed = {workflow.key: workflow.active_catalog_version for workflow in uow.workflows.list()}
                    if not all(installed.get(key, 0) >= catalog.catalog_version for key in managed_keys):
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
    if readback is not None:
        print(readback.model_dump_json(by_alias=True))
    print(f"Alembic обновлён до head для {protocol}")

    print("Начальные каталоги загружены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
