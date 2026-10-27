"""Serve a disposable loopback UI/API fixture; never opens the runtime database."""

import argparse
import json
import os
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18418)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / "fixture.db"
    if database.exists():
        parser.error("Choose a new directory; existing databases are never reset.")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Configure the isolated owner before importing modules that capture settings.
    os.environ.update(
        DATABASE_URL="sqlite:///" + str(database), AUTH_ISSUER="", UI_BASE_PATH="/workflow",
        UI_PLATFORM_ORIGIN="", PLATFORM_SERVICES_URL="",
    )
    from project_workflow import config
    from project_workflow.infrastructure.db.uow import SAUnitOfWork
    from project_workflow.interfaces.ui import app
    from tests._db_helpers import prepare_sqlite_uow

    with SAUnitOfWork(os.environ["DATABASE_URL"]) as uow:
        prepare_sqlite_uow(uow)
        profession = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
        assert profession is not None and profession.id is not None
        workflows = []
        for number in range(2):
            workflow_id = uow.workflows.create({
                "key": f"incremental-fixture-{number}", "name": f"Процесс {number + 1}",
            })
            uow.workflows.assign_profession(workflow_id, profession.id)
            default = uow.workflows.get_mode_by_key(workflow_id, "default")
            assert default is not None
            modes = [default.id, uow.workflows.create_mode({
                "workflow_id": workflow_id, "key": "review", "name": "Проверка", "mode_order": 2,
            })]
            for mode_id in modes:
                for index in range(3):
                    uow.phases.create({
                        "workflow_id": workflow_id, "mode_id": mode_id, "code": f"step-{index}",
                        "name": f"Этап {number + 1}.{mode_id}.{index + 1}",
                        "phase_order": index + 1, "execution_type": "sync",
                    })
            workflows.append({"id": workflow_id, "modes": modes})
        uow.commit()
        info = {"fixture": "workflow-incremental-owned", "profession_id": profession.id, "workflows": workflows}
    (directory / "fixture.json").write_text(json.dumps(info), encoding="utf-8")

    async def metadata(request: Request) -> JSONResponse:
        return JSONResponse(info)

    wrapped = Starlette(routes=[Route("/__fixture", metadata), Mount("/workflow", app=app)])
    uvicorn.run(wrapped, host="127.0.0.1", port=args.port, lifespan="off", log_level="warning")


if __name__ == "__main__":
    main()
