"""Render the opt-in Base candidate from preserved technical catalog identities."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "project_workflow/references/base_sdlc_catalog_v1.json"

# Ordered role actions are content; rendering does not install or route assignments.
ACTIONS = {
    ("project_manager", "draft"): [
        (
            "requirements-analysis",
            (
                "Выяснить бизнесовую цель, actors, желаемый результат, ограничения и общие "
                "требования; не проектировать архитектуру и технические children."
            ),
        ),
        (
            "tracker-operator",
            (
                "Сформировать Draft/В работе из первого сообщения, временное название 3–4 слова; "
                "уточнять по одному значимому вопросу в том же чате, принимая свободный ответ и "
                "варианты."
            ),
        ),
        (
            "tracker-operator",
            (
                "Через guarded Draft capability и CAS уточнить title/description, priority, "
                "estimates/dates, component/milestone/labels, assignee, parent/dependencies/links, "
                "существующие attachment refs того же проекта. Project/kind/stage/status не входят в "
                "patch."
            ),
        ),
        (
            "requirements-analysis",
            (
                "Проверить название: ровно 3–4 смысловых слова, максимум 80 символов; изложить "
                "scope/non-goals и измеримые acceptance criteria."
            ),
        ),
        (
            "tracker-operator",
            (
                "Показать итог exact Draft revision и получить её явное пользовательское "
                "подтверждение. После изменения revision прежнее подтверждение недействительно. "
                "Backlog pickup выполняет backend автоматически; PM не запускает Analyst."
            ),
        ),
    ],
    ("analyst", "analysis"): [
        (
            "requirements-analysis",
            (
                "Собрать разрешённые источники, PM framing, предметные факты и отвеченные вопросы; "
                "отделить неизвестное от фактов и не расширять scope."
            ),
        ),
        (
            "domain-modeling",
            (
                "Описать glossary, actors, bounded contexts, source of truth, инварианты и "
                "project/tenant boundaries без выбора реализации."
            ),
        ),
        (
            "requirements-analysis",
            (
                "Создать versioned requirements со stable refs, источниками, scope/non-goals, "
                "acceptance criteria и positive/negative/boundary/permission/partial-failure cases."
            ),
        ),
        (
            "workflow-writing-plans",
            (
                "Построить coverage matrix requirement → источник → criterion → проверка; устранить "
                "противоречия или задать один конкретный вопрос с durable checkpoint."
            ),
        ),
        (
            "tracker-operator",
            (
                "Сохранить анализ через owner capability и прочитать accepted revision/evidence refs;"
                " не создавать архитектурные подзадачи вместо Architect."
            ),
        ),
    ],
    ("architect", "decomposition"): [
        (
            "solution-architecture",
            (
                "Проверить существующие capabilities и reuse до нового механизма; назначить owners и "
                "проследить producer/storage/API/consumer/failure/tests."
            ),
        ),
        (
            "domain-modeling",
            (
                "Зафиксировать решения, интерфейсы, compat/versioning, tenant/permission rules, "
                "pinned inputs и dataflow; изменения source of truth требуют принятого ADR."
            ),
        ),
        (
            "solution-architecture",
            (
                "Декомпозировать по проверяемым результатам: каждому child дать scope, frozen "
                "requirements coverage, criteria, allowed paths, зависимости и integration contract."
            ),
        ),
        (
            "tracker-operator",
            (
                "Через требуемую capability materialize настоящие children и parent/dependency links "
                "в том же проекте; dependency направлена dependent → dependency. Проверить DAG "
                "зависимостей, orphan и coverage; пустой набор не открывает barrier."
            ),
        ),
        (
            "workflow-writing-plans",
            (
                "Сохранить accepted decomposition revision и прочитать реальные IDs/links/coverage. "
                "Root ждёт successful DevOps всех обязательных children активной revision без "
                "активного Architect run; изменённая revision, reopened child и stale evidence "
                "закрывают barrier."
            ),
        ),
        (
            "solution-architecture",
            (
                "Описать интеграцию root, риски, rollback и порядок готовых children; согласовать "
                "candidate source refs без ручного выполнения children."
            ),
        ),
    ],
    ("developer", "initial"): [
        (
            "forge-operator",
            (
                "Проверить issued attempt workspace, pinned source/branch, paths и fencing; не "
                "создавать checkout и не выбирать slot. Delivery реализует назначенный child; "
                "aggregate допустим только после Tracker barrier."
            ),
        ),
        (
            "test-driven-development",
            (
                "Связать production behavior с frozen criteria, получить воспроизводимый RED где "
                "практично и реализовать минимальный GREEN без ослабления checks."
            ),
        ),
        (
            "repo-workflow",
            (
                "Работать только в permitted paths. В aggregate состыковать outputs всех обязательных"
                " children активной decomposition revision и реализовать root integration criteria, "
                "не повторяя их delivery заново."
            ),
        ),
        (
            "test-driven-development",
            (
                "Проверить positive/negative, permissions, retry/stale и применимые regressions "
                "быстрыми package checks. Один общий gate выполняет назначенный Forge milestone, не "
                "каждый slice."
            ),
        ),
        (
            "forge-operator",
            (
                "Проверить разрешённый diff и отсутствие secrets/cache/build мусора; commit/push "
                "только собственные изменения при наличии diff, readback exact remote SHA и clean "
                "workspace. Candidate receipt готовит Forge по build policy DevOps; Developer mode "
                "build отсутствует."
            ),
        ),
    ],
    ("developer", "rework"): [
        (
            "tracker-operator",
            (
                "Прочитать frozen ReworkRequest именно текущего cycle: source Review/Testing, "
                "reproduction, expected/actual и evidence. Не выбирать mode или менять findings."
            ),
        ),
        (
            "workflow-systematic-debugging",
            (
                "Воспроизвести каждый finding на pinned candidate и локализовать первопричину; "
                "unknown infra issue вернуть как blocker, не скрытый workaround."
            ),
        ),
        (
            "test-driven-development",
            (
                "Исправить все назначенные findings и добавить regression checks; delivery ограничен "
                "child, aggregate исправляет интеграцию root при сохранённом barrier."
            ),
        ),
        (
            "repo-workflow",
            (
                "Перепроверить requirement coverage и relevant regressions, не расширяя permitted "
                "paths и не переписывая предыдущие cycles/evidence."
            ),
        ),
        (
            "forge-operator",
            (
                "После проверки diff выполнить commit/push при изменениях, remote SHA readback и "
                "clean workspace. Unknown push reconcile по исходному key. Retry увеличивает attempt,"
                " не cycle; backend после rework вернёт в Review, затем Testing."
            ),
        ),
    ],
    ("reviewer", "delivery"): [
        (
            "forge-operator",
            (
                "Прочитать exact child base/head/candidate refs и принятые Forge gates; не подменять "
                "target свежей веткой или старым pipeline."
            ),
        ),
        (
            "exact-code-review",
            (
                "Независимо проверить diff, ownership/dataflow, frozen child criteria, "
                "интерфейсы/dependencies, persistence/migrations, tenant permissions и совместимость."
            ),
        ),
        (
            "exact-code-review",
            (
                "Проверить production tests, retry/idempotency/stale/restart и hygiene; read-only "
                "роль не меняет код и не пушит reviewed branch."
            ),
        ),
        (
            "tracker-operator",
            (
                "Если нужен implementation fix — сформировать needs_rework findings с severity, "
                "location/ref, reproduction, expected/actual и evidence. При полном соответствии "
                "решение passed; недостаток данных означает вопрос, не решение."
            ),
        ),
    ],
    ("reviewer", "integration"): [
        (
            "forge-operator",
            (
                "Прочитать exact root integration candidate и barrier receipt всех обязательных "
                "children активной decomposition revision; stale child закрывает gate."
            ),
        ),
        (
            "exact-code-review",
            (
                "Проверить совместимость children, общие contracts/dataflow и coverage root "
                "требований, aggregate diff, migration/permission boundaries."
            ),
        ),
        (
            "exact-code-review",
            (
                "Проверить реальные integration/regression tests, idempotency/restart/stale и "
                "отсутствие degradation. Не исправлять реализацию и не пушить проверяемую ветку."
            ),
        ),
        (
            "tracker-operator",
            (
                "Сформировать passed либо воспроизводимые frozen needs_rework findings общего root; "
                "не подменять root review суммой child reports."
            ),
        ),
    ],
    ("tester", "delivery"): [
        (
            "forge-operator",
            (
                "Получить assigned child verification target receipt; проверить "
                "source/artifact/config identity и доступность. ACTIVE/healthy ещё не PASS."
            ),
        ),
        (
            "deployed-acceptance",
            (
                "Проверить каждый frozen child criterion через разрешённые API/UI tools; "
                "positive/negative/boundary/empty/permission/tenant и dependency contracts."
            ),
        ),
        (
            "workflow-systematic-debugging",
            (
                "При дефекте сохранить reproducer, expected/actual, severity и exact runtime "
                "evidence; выполнить применимые retry/restart/regressions без исправления кода."
            ),
        ),
        (
            "deployed-acceptance",
            (
                "Сохранить typed test report/coverage и screenshots/API refs. Tool/target unavailable"
                " — blocker, не иной runtime или фиктивный PASS. Owner закрывает target и "
                "подтверждает cleanup receipt."
            ),
        ),
    ],
    ("tester", "integration"): [
        (
            "forge-operator",
            (
                "Проверить assigned root verification target exact identity, candidate и активный "
                "child barrier; не использовать только child targets."
            ),
        ),
        (
            "deployed-acceptance",
            (
                "Пройти общий пользовательский сценарий root и стыки всех обязательных children, "
                "проверить end-to-end coverage requirements и regressions."
            ),
        ),
        (
            "workflow-systematic-debugging",
            (
                "Проверить negative/tenant/permissions, duplicate/stale/restart/partial failure, "
                "долгие сообщения и UI при применимости; записать воспроизводимые findings, не чинить"
                " реализацию."
            ),
        ),
        (
            "deployed-acceptance",
            (
                "Сохранить root acceptance test report и exact evidence; passed либо needs_rework "
                "findings, не rollup children. Owner-issued cleanup receipt обязателен до "
                "освобождения target."
            ),
        ),
    ],
    ("devops", "delivery"): [
        (
            "forge-operator",
            (
                "Сверить child candidate source SHA с Review/Testing и existing mandatory Forge "
                "pipeline. Организовать build через Forge по назначенной milestone policy, не после "
                "каждого slice и не повторно для того же verified candidate."
            ),
        ),
        (
            "exact-sha-deployment",
            (
                "Заморозить candidate manifest с source/artifact/image/config digests, permissions, "
                "target, accepted gates и rollback baseline; проверить data compatibility и required "
                "approvals."
            ),
        ),
        (
            "exact-sha-deployment",
            (
                "Выпустить exact child candidate штатной Forge capability. При unknown сначала "
                "lookup/reconcile исходного operation key; не exploratory deploy и не feature write."
            ),
        ),
        (
            "exact-sha-deployment",
            (
                "Проверить served identity, health, сохранность данных и child acceptance; сохранить "
                "trusted deployment/acceptance receipt. Этот receipt удовлетворяет child barrier, но "
                "не завершает root."
            ),
        ),
    ],
    ("devops", "integration"): [
        (
            "forge-operator",
            (
                "Сверить root integration candidate, active decomposition barrier, Review/Testing и "
                "mandatory exact-head Forge gates; не пересобирать другой SHA ради release."
            ),
        ),
        (
            "exact-sha-deployment",
            (
                "Зафиксировать root candidate manifest, target/promotion policy, "
                "artifact/image/config digests, approvals, data compatibility и rollback baseline."
            ),
        ),
        (
            "exact-sha-deployment",
            (
                "Выпустить только назначенный root candidate через Forge, reconcile unknown deploy; "
                "выполнять rollback только к заранее verified baseline и по owner policy."
            ),
        ),
        (
            "exact-sha-deployment",
            (
                "Проверить served source/digests, health/data preservation и собственный root "
                "Deployment с business acceptance. Child rollup, зелёный build и healthy контейнер "
                "отдельно не завершают root."
            ),
        ),
    ],
}


OUTPUTS = {
    ("project_manager", "draft"): (
        "Exact confirmed Draft revision с business framing и полной допустимой metadata.",
        "Confirmation не устарело; имя 3–4 слова до 80 символов; required business answers получены.",
    ),
    ("analyst", "analysis"): (
        "Versioned requirements, glossary, source/criterion coverage и negative scenarios.",
        "Каждое требование имеет источник и проверяемый criterion; неизвестное не выдано за факт.",
    ),
    ("architect", "decomposition"): (
        "Accepted decomposition revision, реальные child IDs/parent/dependency links и coverage matrix.",
        "Children непустые и same-project; dependency DAG валиден; requirements coverage полна.",
    ),
    ("developer", "initial"): (
        "Scoped implementation/regression checks, permitted diff, commit/push remote SHA и candidate refs.",
        "Все assigned criteria реализованы; aggregate barrier актуален; owned workspace clean.",
    ),
    ("developer", "rework"): (
        "Finding-to-fix regression matrix, frozen cycle refs, remote SHA и новый candidate.",
        "Каждый frozen finding устранён и regression проверен; attempt не создал новый cycle.",
    ),
    ("reviewer", "delivery"): (
        "Child exact candidate review report: passed либо воспроизводимые findings.",
        "Review covers child criteria/contracts; reviewed branch неизменна; gates относятся к exact SHA.",
    ),
    ("reviewer", "integration"): (
        "Root integration review и cross-child requirement coverage/findings.",
        "Все active children и их стыки проверены; root review не сумма child reports.",
    ),
    ("tester", "delivery"): (
        "Child TestReport: scenarios, expected/actual, safe API/UI evidence и cleanup receipt.",
        "Child criteria реально проверены на assigned exact target; findings воспроизводимы.",
    ),
    ("tester", "integration"): (
        "Root end-to-end TestReport, integration/regression evidence и cleanup receipt.",
        "Проверен общий root пользовательский сценарий и negative cases, а не только child targets.",
    ),
    ("devops", "delivery"): (
        "Child candidate/pipeline manifest, served identity, deployment/acceptance и rollback refs.",
        "Exact candidate и required approvals совпали; child Deployment/acceptance verified.",
    ),
    ("devops", "integration"): (
        "Root exact candidate manifest и собственные Deployment/acceptance/rollback receipts.",
        "Root served identity/health/data compatibility и business acceptance подтверждены отдельно.",
    ),
}


def render(skills_root: Path, skills_sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", skills_sha):
        raise ValueError("exact skills commit SHA required")
    catalog = json.loads((ROOT / "project_workflow/references/hermes_sdlc_catalog_v1.json").read_text(encoding="utf-8"))
    manifest = json.loads((skills_root / "manifest.json").read_text(encoding="utf-8"))
    catalog["catalog_version"] = 3
    catalog["skills_source"] = {
        "repository": "https://github.com/FerrPOINT/fleet-control.git",
        "revision": skills_sha,
        "manifest_path": "agent-skills/manifest.json",
        "manifest_schema": manifest["schema"],
    }
    for workflow in catalog["workflows"]:
        role = workflow["role_key"]
        declaration = manifest["roles"][role]
        assert workflow["hermes_namespace"] == declaration["namespace"]
        assert workflow["hermes_profile"] == declaration["profile"]
        workflow["description"] = (
            f"Base candidate: {role}; назначение Tracker, исполнение Fleet, receipts Workflow/Forge; не установлен."
        )
        workflow["skill_allowlist"] = declaration["physicalSkills"]
        for mode in workflow["modes"]:
            key = mode["key"]
            actions = ACTIONS[role, key]
            scopes = "/".join(mode["execution_scopes"])
            admission = [
                (
                    "tracker-operator",
                    (
                        "Первый вызов ровно project-workflow --json step --task <session>; admission "
                        "проверяет backend assignment. Затем читать Task, все comments и attachments, "
                        "links/history и frozen inputs текущей revision, не выбирая mode/scope/workspace из "
                        "prompt."
                    ),
                ),
                (
                    "tracker-operator",
                    f"Сверить Task/root/project/revisions, agent/role={role}, namespace/profile, "
                    f"workflow/mode={key}, scope={scopes}, run/cycle/attempt, fencing/operation key, "
                    "configuration hashes и owner-issued workspace lease. Missing/mismatch — fail-closed до модели.",
                ),
                (
                    "immutable-evidence-reporting",
                    (
                        "Проверить pinned requirements/decomposition, predecessor receipts, доступ к каждому "
                        "input и allowed skills/actions/paths; stale evidence, закрытый barrier или "
                        "отсутствующая capability не подменяются manual action."
                    ),
                ),
            ]
            terminal = "publishDraft" if role == "project_manager" else "completeAssignedStage"
            outcome = (
                "outcome passed или needs_rework с непустыми frozen findings"
                if role in {"reviewer", "tester"}
                else "outcome passed"
            )
            ending = [
                (
                    "immutable-evidence-reporting",
                    (
                        "Перечитать результат и exact revisions/receipts, проверить requirement coverage, "
                        "checks и ограничения. При Git changes обязательны permitted diff, commit/push, "
                        "remote SHA и clean workspace; read-only роли не пушат reviewed branch. Не создавать "
                        "пустые commits."
                    ),
                ),
                (
                    "tracker-operator",
                    (
                        "При неизвестном эффекте dispatch/push/deploy/comment сначала owner lookup/reconcile "
                        "прежнего operation key. Durable terminal ACK либо безопасный awaiting-input "
                        "checkpoint предшествует owner release; модель сама не освобождает slot."
                    ),
                ),
                (
                    "immutable-evidence-reporting",
                    "Подготовить итоговый Business Markdown comment (только compatibility marker валидатора; "
                    "в Base это Task Tracker comment): результат, coverage требований, проверки, evidence "
                    "и ограничения; для Architect — реальные children/dependencies, Reviewer/Tester — "
                    "решение/findings, DevOps — exact candidate/acceptance. Передать принятый report через "
                    "project-workflow --json step --task <session> --report <report>; дождаться complete=true, "
                    "сохранить и прочитать итоговый комментарий, затем запросить только "
                    f"{terminal} как owner capability, не выдуманную CLI-команду, с {outcome}. "
                    "При недостаточных данных one concrete question и durable awaiting-input handshake "
                    "с unfinished phase; terminal action запрещён.",
                ),
            ]
            for index, instructions in enumerate((admission, actions, ending)):
                phase = mode["phases"][index]
                phase["name"] = ["Допуск и входы", "Действия роли", "Проверка и передача"][index]
                phase["description"] = f"{workflow['name']}/{key}: {phase['name']}; scope {scopes}, candidate Base."
                phase["instructions"] = [
                    {"description": text, "skills": sorted({"project-workflow-executor", skill})}
                    for skill, text in instructions
                ]
                phase["checks"] = [
                    "Exact assignment, role/mode/scope/configuration совпадают; технические IDs не выбирает модель.",
                    "Все инструкции текущей фазы выполнены по порядку с фактическим evidence; blocker не PASS.",
                    "Requirements/input revisions, tenant permissions и operation key не устарели.",
                ]
                phase["evidence"] = [
                    "Assignment/cursor и pinned input refs, requirement/decomposition revisions.",
                    "Принятый phase report с coverage, checks, safe evidence и ограничениями.",
                    "Owner receipt текущей операции либо конкретный blocker/awaiting-input checkpoint.",
                ]
                if index > 0:
                    output, gate = OUTPUTS[role, key]
                    phase["checks"].append(gate)
                    phase["evidence"].append(output)
                if index == 2:
                    phase["checks"].append(
                        "Workflow complete=true receipt и итоговый comment readback получены; "
                        "недостающий gate/approval сохраняет стадию незавершённой."
                    )
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, required=True)
    parser.add_argument("--skills-sha", required=True)
    args = parser.parse_args()
    CANDIDATE.write_text(
        json.dumps(render(args.skills_root, args.skills_sha), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Rendered explicit candidate only; active catalog/bootstrap unchanged")
