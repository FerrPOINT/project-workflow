# Base SDLC candidate v1

Статус: configuration-only, не установлен, 2026-10-02.
Отдельный файл: `project_workflow/references/base_sdlc_catalog_v1.json`.
Сохранены technical schema `relevanter-project-workflow-catalog/v1`, workflow keys,
namespace/profile, mode keys и 33 phase codes существующего каталога.
Семь workflow, 11 modes, три упорядоченные фазы каждого режима. Version 3 — отдельный
candidate, не переключение default catalog version 2.

| Роль | Mode | Scope |
| --- | --- | --- |
| Project Manager | draft | business |
| Analyst | analysis | business |
| Architect | decomposition | business |
| Developer | initial, rework | delivery, aggregate (независимый scope) |
| Reviewer | delivery, integration | delivery, aggregate соответственно |
| Tester | delivery, integration | delivery, aggregate соответственно |
| DevOps | delivery, integration | delivery, aggregate соответственно |

Фазы: exact step admission → полный порядок действий роли → accepted report,
complete=true, итоговый комментарий и разрешённая owner terminal capability.
Количество инструкций не ограничено тремя. Публичный CLI остаётся step/history;
его --task/--report/--json сверены с interfaces/cli/ui.py и core.py.

## Проверка без установки

```bash
python -c "from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog; load_managed_catalog('project_workflow/references/base_sdlc_catalog_v1.json'); print('PASS')"
python scripts/verify_base_sdlc_candidate.py --skills-root ../fleet-control/agent-skills
python -m unittest discover -s tests/base_candidate -v
```

`Business Markdown comment` оставлен только как literal compatibility marker
текущего валидатора. Его смысл здесь — Task Tracker comment. `publishDraft` и
`completeAssignedStage` — target capabilities Tracker, не новые CLI-команды.
Ни marker, ни schema не возвращают ownership Relevanter Business.

## Assignment/receipt v1: оставшаяся адаптация

Workflow владеет каталогом и technical cursor, а не Task lifecycle. Admission
сравнивает exact Tracker assignment, Fleet config и Forge workspace lease перед
моделью. Report/history keyed task+mode+scope+cycle+phase+assignment/run fence.
Accepted terminal receipt фиксирует complete=true, assignment/result hash,
catalog/config/skills hashes и cursor revision. Task completion остаётся Tracker.
Повтор key/payload возвращает receipt; иной payload conflict; stale run/revision
не продвигает cursor. Resume требует owner checkpoint ACK, fresh lease/run и CAS
rebind unfinished phase при прежних mode/scope/cycle/attempt.

Текущий runtime exporter содержит Business-routing/workspace metadata. Его
адаптация к Tracker/Fleet/Forge является отдельной implementation задачей;
экспорт этого candidate нельзя считать готовой runtime конфигурацией Base.
Default catalog, migrations, bootstrap, runtime token config и pinned history
не изменяются. Установка требует интеграционной вехи с verified capabilities.
