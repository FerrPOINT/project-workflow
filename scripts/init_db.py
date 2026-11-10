#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from project_workflow.config import get_settings
from project_workflow.domain.exceptions import ConflictError
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


def main(argv: list[str] | None = None) -> int:
    _configure_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish-packaged-catalog-from", metavar="MANIFEST_SHA256",
        help="Select the packaged catalog over this exact installed source manifest",
    )
    expected_manifest = parser.parse_args(argv or []).publish_packaged_catalog_from
    readback = None
    try:
        settings = get_settings()
        if expected_manifest is not None and settings.PROJECT_WORKFLOW_MODE == "standalone":
            raise ValueError("Packaged catalog publication requires platform mode")
        engine = get_engine(settings.DATABASE_URL)
        with initialization_transaction(engine) as connection:
            ensure_migrated(connection)
            with SAUnitOfWork(connection) as uow:
                uow.lock_catalog_state()
                if settings.PROJECT_WORKFLOW_MODE == "standalone":
                    from project_workflow.application.standalone import validate_database

                    validate_database(uow)
                elif expected_manifest is not None:
                    from project_workflow.application.catalog_publication import publish_packaged_catalog

                    readback = publish_packaged_catalog(uow, expected_manifest)
                else:
                    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

                    readback = ensure_single_task_catalog(uow)
    except DatabaseRecreateRequired as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except DatabaseUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except (ConflictError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError):
        print("Не удалось инициализировать базу данных", file=sys.stderr)
        return 1
    protocol = settings.DATABASE_URL.split(":")[0]
    if readback is not None:
        print(readback.model_dump_json(by_alias=True))
    print(f"Alembic обновлён до head для {protocol}")

    print("Начальные каталоги загружены" if readback is not None
          else "Самостоятельная БД готова; каталог создаётся явно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
