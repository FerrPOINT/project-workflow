"""Real Workflow UI with a disposable SQLite catalog for Base browser tests."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import uvicorn


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="base-platform-workflow-") as temporary:
        root = Path(temporary)
        os.environ["DATABASE_URL"] = f"sqlite:///{root / 'workflow.db'}"
        os.environ["AUTH_ISSUER"] = "http://127.0.0.1:17901"
        os.environ["AUTH_INTERNAL_BASE_URL"] = "http://127.0.0.1:17901"
        os.environ["AUTH_PUBLIC_ORIGIN"] = "http://127.0.0.1:17952"
        os.environ["AUTH_SESSION_SECRET"] = "platform-fixture-only-encrypted-cookie-secret"
        os.environ["UI_PLATFORM_ORIGIN"] = "http://127.0.0.1:17990"
        os.environ["PLATFORM_SERVICES_URL"] = "http://127.0.0.1:17901/api/v1/runtime/services"
        from project_workflow import config
        from project_workflow.infrastructure.db.session import ensure_migrated
        from project_workflow.infrastructure.db.uow import SAUnitOfWork
        from project_workflow.interfaces.ui.app import create_app
        from tests._db_helpers import prepare_sqlite_uow

        config.get_settings.cache_clear()
        seed = root / "legacy_unmanaged_seed.json"
        shutil.copyfile(config.LEGACY_UNMANAGED_SEED_PATH, seed)
        config.LEGACY_UNMANAGED_SEED_PATH = seed
        ensure_migrated()
        with SAUnitOfWork(os.environ["DATABASE_URL"]) as uow:
            prepare_sqlite_uow(uow)
        uvicorn.run(create_app(), host="127.0.0.1", port=17952, log_level="warning")


if __name__ == "__main__":
    main()
