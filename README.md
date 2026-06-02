# project-workflow-cli

> Декларативный engine для командного workflow. 26 фаз, параллельное делегирование агентам, rollback-циклы, двойной вывод (Rich + JSON).

## Что это

**project-workflow-cli** — CLI-инструмент для жёсткого пофазового управления задачами разработки. Каждая задача проходит через декларативно описанные фазы (YAML), с mandatory evidence на каждом шаге. Поддерживает rollback-циклы (QA → Implement → Review → QA, max 3 cycles) и параллельное делегирование sub-агентам.

**Ключевые особенности:**
- **Декларативные фазы**: единый источник истины в `references/phases.yaml`
- **Двойной интерфейс**: Rich-таблицы для человека, JSON для агентов (`--json`)
- **Rollback engine**: автоматический откат при gate failure с очисткой checkpoints
- **Параллельные агенты**: `delegate` / `delegate-batch` команды для multi-agent workflow
- **Atomic state**: SQLite в планах, сейчас JSON с очисткой

## Установка

```bash
git clone https://github.com/FerrPOINT/project-workflow-cli.git
cd project-workflow-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI Команды

### Для человека (Rich)
```bash
hrflow init AAT-123 TASKNEIROKLYUCH-456 "Название задачи"
hrflow phase AAT-123 0
hrflow next AAT-123
hrflow status AAT-123
hrflow verify AAT-123
hrflow merge-check AAT-123
hrflow list-phases
hrflow playbook AAT-123 "0.6"
hrflow rollback AAT-123 7.6 --reason "QA FAIL: auth broken"
hrflow delegate AAT-123 reviewer
hrflow delegate-batch AAT-123 reviewer,qa
hrflow jobs
```

### Для агента (JSON)
```bash
hrflow --json init AAT-123 TASKNEIROKLYUCH-456 "Название"
hrflow --json next-step AAT-123
hrflow --json check-env
hrflow --json playbook AAT-123 "0.6"
hrflow --json rollback AAT-123 7.6 --reason "QA FAIL"
```

## Архитектура

```
wartz_workflow/
├── cli.py              # Click CLI с двойным выводом (Rich + JSON)
├── config.py           # Константы, пути, API endpoints
├── state.py            # Состояние задач (JSON + progress.json)
├── phases.py           # Управление фазами, чеклисты
├── schema.py           # YAML → dataclasses парсер
├── engine.py           # Движок выполнения фаз
├── verify.py           # verify-suite, .gitignore, токены
├── jira_gitlab.py      # Интеграция Jira REST + GitLab API
├── profiles.py         # Реестр агент-профилей
├── jobs.py             # Job tracking для делегирования
├── rollback.py         # Rollback engine с cycle tracking
└── references/
    └── phases.yaml     # Декларативное описание 26 фаз

tests/
├── test_cli_integration.py
├── test_jobs.py
├── test_phases.py
├── test_profiles.py
├── test_rollback.py
├── test_state.py
└── test_verify.py
```

## Тестирование

```bash
pytest tests/ -v --cov=wartz_workflow --cov-report=term
```

**Текущий статус:** 58 тестов проходят, покрытие ~47% (цель: 80%).

## Workflow фазы (сокращённо)

| Фаза | Название | Роль | Gate |
|------|----------|------|------|
| 0.6 | Research | wartzresearcher | — |
| 1 | Understand | coder | — |
| 1.5 | Parallel agents | — | — |
| 2 | Requirements | coder | — |
| 3 | Plan | coder | CriticGate (3.5) |
| 4 | Implement | coder | — |
| 4.5 | Review gate | reviewer | — |
| 5 | Review | reviewer | — |
| 5.5 | CriticGate-PostReview | critic | — |
| 6 | Test | coder | — |
| 7 | QA Ready | — | — |
| 7.5 | QA Execute | qa | — |
| 7.6 | QA Verify | qa | — |
| 8 | Done | — | Jira transition |

## Rollback циклы

```bash
# QA нашёл баг — откат к Implement (Phase 4)
hrflow rollback AAT-123 7.6 --reason "QA FAIL: login broken"
# → Сброшены фазы: 4, 4.5, 5, 5.5, 6, 7, 7.5, 7.6
# → current_phase = "4", cycle = 1/3

# Review нашёл SQL injection — тот же откат
hrflow rollback AAT-123 7.5 --reason "Review: fix SQL injection"

# CriticGate не пропустил план — откат к Plan (Phase 3)
hrflow rollback AAT-123 3.5 --reason "CriticGate: redesign needed"
```

## CI / CD

```yaml
# .github/workflows/ci.yml (планируется)
- pytest tests/ -v --cov=wartz_workflow
- ruff check wartz_workflow/
- mypy wartz_workflow/
```

## Лицензия

MIT

## Автор

Александр Жуков (FerrPOINT)
