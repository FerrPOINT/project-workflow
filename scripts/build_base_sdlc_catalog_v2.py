"""Build the next initial catalog from the exact configured-tools Base package."""

import argparse
import copy
import json
from pathlib import Path

from project_workflow.infrastructure.base_package import load_pinned_package
from project_workflow.infrastructure.db.managed_catalog import CatalogSource

ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "6e1d190ecd15b772b1066c472f864b8becb3f97a"
OUTPUT = ROOT / "project_workflow/references/base_sdlc_catalog_v2.json"
PURPOSES = {
    "project_manager": "Уточнение задачи, подготовка требований и подтверждение их владельцем.",
    "analyst": "Анализ требований, предметной области и критериев приёмки.",
    "architect": "Архитектура решения, декомпозиция на связанные задачи и покрытие требований.",
    "developer": "Разработка, исправление замечаний и интеграция результата.",
    "reviewer": "Независимая проверка кода, архитектуры, контрактов и результатов проверки.",
    "tester": "Проверка критериев приёмки и пользовательских сценариев.",
    "devops": "Сборка и выпуск согласованного результата с проверкой и планом отката.",
}

ADMISSION = (
    "Первый вызов — настроенный Workflow tool: в PM MCP это workflow_step с command.report: null, "
    "исходным step_operation_key и выданными runtime operation_id/session_run_id. Не придумывать IDs. "
    "CLI project-workflow --json step --task <session> разрешён только если действительно выдан в configured "
    "tool inventory; skill не устанавливает CLI и не даёт shell. После exact admission читать Task, все "
    "доступные comments и attachments, links/history и frozen inputs; history только через предоставленный read tool."
)
CAPABILITIES = (
    "Проверять allowed skills/actions/paths и pinned input revisions для текущего назначенного шага. "
    "Если необходимая этому шагу capability отсутствует, сохранить точный blocker; не обходить generic Task patch "
    "или shell. Отсутствие инструмента будущей стадии не блокирует доступные действия текущей фазы. "
    "Модель не выбирает routing, mode/scope, priority, workspace, skills installation или другого агента."
)
REPORT = (
    "Содержательный phase report передать тем же configured Workflow tool; в PM MCP — workflow_step с "
    "непустым command.report и исходным ключом этой операции. Uncertain retry использует прежние key/body; "
    "следующая операция — собственный key. Продолжать только по возвращённой фазе до принятого complete=true. "
    "Не выводить completion из текста или process exit. Итоговый Task Tracker comment: результат, coverage, "
    "checks, exact evidence и ограничения."
)
PM_ACTIONS = [
    "Через tracker_context прочитать назначенный Task и проект; через tracker_clarifications и tracker_requirements "
    "прочитать вопросы, ответы и редакции требований. Выяснить бизнес-цель, actors, scope, constraints и acceptance; "
    "не выполнять архитектуру, код или техническую декомпозицию за следующие профессии.",
    "Сформировать Draft/В работе из свободного запроса: название 3–4 смысловых слова до 80 символов, бизнесовое "
    "описание, требования и измеримые acceptance criteria. Менять только разрешённую структуру Draft с CAS и "
    "same-project checks; project/kind/stage/status не входят в универсальный patch.",
    "Сохранить требования через настроенный tracker_publish_revision. Не превращать имена общих capabilities "
    "в вымышленные MCP tools или CLI-команды; текущий PM inventory содержит ровно шесть tools из Base.",
    "По одному значимому вопросу через tracker_publish_question; варианты допускают свободный ответ. "
    "При ожидании данных сохранить unfinished phase и durable checkpoint, затем ждать owner-controlled resume.",
    "Показать human owner exact requirements revision и content_hash. PM не вызывает confirm, не подделывает consent "
    "и не запускает Analyst; после изменения Draft прежнее подтверждение недействительно.",
]


def terminal(role: str) -> str:
    result = "outcome passed"
    if role in {"reviewer", "tester"}:
        result += " либо needs_rework с frozen findings"
    common = (
        f"После accepted project-workflow report и complete=true оформить {result}, итоговый Task Tracker comment, "
        "coverage, checks и exact evidence. "
    )
    if role == "project_manager":
        handoff = (
            "Последний business шаг — действие human owner: confirmation exact revision + content_hash. "
            "PM никогда не вызывает confirm и не подтверждает требования runtime credential. Через доступный owner "
            "readback проверить matching Backlog receipt и server-created Analysis intent. Сохранённый ответ и "
            "Workflow PASS не заменяют consent. Отдельного machine publish/terminal tool в шести PM tools нет. "
            "До owner confirmation или readback явно ждать владельца; Analysis intent не доказывает Analyst dispatch. "
        )
    else:
        handoff = (
            "Последний шаг — вызвать реально предоставленный guarded Tracker terminal tool с исходным operation key, "
            "assignment/revision/fence, frozen input revisions и typed result/evidence. Запросить разрешённый status "
            "и следующий stage; их выбирает сервер. Проверить сохранённый matching receipt/readback. При отсутствии "
            "producer tool сохранить blocker; комментарий, Workflow complete и process exit "
            "не завершают business stage. "
            "Uncertain эффект сначала reconcile исходной операции, не новый key. Stop ACK не освобождает capacity: "
            "release требует проверенного owner terminal/stop proof. "
        )
    return common + handoff + (
        "Недостаток входов — one concrete question и durable awaiting-input checkpoint при unfinished phase, "
        "не успешный terminal handoff."
    )


def build(skills_root: Path) -> dict:
    original = ROOT / "project_workflow/references/base_sdlc_catalog_v1.json"
    catalog = copy.deepcopy(json.loads(original.read_text("utf-8")))
    catalog["catalog_version"] = 4
    catalog["skills_source"]["revision"] = BASE_REVISION
    manifest = load_pinned_package(skills_root, CatalogSource.model_validate(catalog["skills_source"]))
    assert set(manifest["roles"]) == {workflow["role_key"] for workflow in catalog["workflows"]}
    for workflow in catalog["workflows"]:
        role = workflow["role_key"]
        workflow["description"] = PURPOSES[role]
        declaration = manifest["roles"][role]
        assert workflow["skill_allowlist"] == declaration["physicalSkills"]
        assert [mode["key"] for mode in workflow["modes"]] == declaration["modes"]
        workflow["terminal_contract"] = "configured-tools"
        for mode in workflow["modes"]:
            first, actions, last = mode["phases"]
            first["instructions"][0]["description"] = ADMISSION
            first["instructions"][-1]["description"] = CAPABILITIES
            if role == "project_manager":
                actions["instructions"] = [
                    {"description": text, "skills": ["project-workflow-executor", "tracker-operator"]}
                    for text in PM_ACTIONS
                ]
                last["checks"][0] = "Exact revision/hash подтверждены human owner; PM не вызывает owner confirm."
                last["evidence"][0] = (
                    "Matching Backlog receipt и Analysis intent либо точное ожидание owner confirmation."
                )
            last["instructions"][-2]["description"] = REPORT
            last["instructions"][-1]["description"] = terminal(role)
            last["checks"].append("Handoff подтверждён matching owner receipt/readback; неизвестный эффект не PASS.")
    assert sum(len(w["modes"]) for w in catalog["workflows"]) == 11
    assert sum(len(m["phases"]) for w in catalog["workflows"] for m in w["modes"]) == 33
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(build(args.skills_root), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if args.output.read_text("utf-8") != content:
            raise ValueError("Catalog differs from its reproducible Base source inputs")
    else:
        args.output.write_text(content, encoding="utf-8", newline="\n")
    print("PASS: exact Base package; seven professions, eleven modes, thirty-three phases")


if __name__ == "__main__":
    main()
