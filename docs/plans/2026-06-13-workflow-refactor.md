# project-workflow — план доработки (audit fix)

> **Для Hermes:** Использовать workflow-subagent-driven-development skill для реализации задач.

**Цель:** Устранить критические архитектурные дефекты, найденные при аудите: детерминизм DB-пути, type mismatch в FOREIGN KEY, dual-state legacy (файлы + БД), dead code, мусор в репозитории.

**Архитектура:** Единственный source of truth — SQLite (`workflow.db`). Все runtime-данные хранятся в БД, никаких параллельных JSON/progress.json/state-файлов. CLI-путь к БД определяется жёстко через `WORKFLOW_DB_PATH` или fallback внутри пакета (не через `expanduser("~")`).

**Стек:** Python 3.10+, SQLite, Click, FastAPI, Pydantic, pytest, transitions.

**Принципы:** TDD (RED-GREEN-REFACTOR), bite-sized задачи (~15-30 мин), commit после каждой задачи, NEVER создавать side-by-side версии файлов.

---

## Фаза 1: Критические hotfixes (нельзя откладывать)

### Задача 1: Детерминизм пути к SQLite (DB Path)

**Objective:** Убрать `os.path.expanduser("~")` как fallback — он даёт разные пути в systemd vs Hermes terminal vs cron. Сделать поведение предсказуемым.

**Файлы:**
- Модифицировать: `project_workflow/db.py:17-18`
- Модифицировать: `tests/conftest.py`
- Модифицировать: `project_workflow/config.py`

**Шаг 1: Тест на детерминизм**

```python
# tests/test_db_path.py
def test_db_path_without_env_uses_package_fallback():
    """Без WORKFLOW_DB_PATH DB должен лежать рядом с пакетом, не в HOME."""
    # При отсутствии env должен быть deterministic путь
    assert str(db.DB_PATH).endswith("project-workflow/workflow.db")

def test_db_path_reads_from_env():
    """WORKFLOW_DB_PATH переопределяет дефолт."""
    with patch.dict(os.environ, {"WORKFLOW_DB_PATH": "/tmp/test-wf.db"}):
        # reimport or use factory
        assert str(db.DB_PATH) == "/tmp/test-wf.db"
```

**Шаг 2: Реализация**

```python
# project_workflow/db.py
# Убрать expanduser fallback. Два режима:
# 1. WORKFLOW_DB_PATH из env — используем как есть (для systemd)
# 2. Нет env — путь внутри пакета: Path(__file__).resolve().parent.parent / "data" / "workflow.db"
#    Это dev-режим, deterministic для всех процессов.

PKG_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("WORKFLOW_DB_PATH", str(PKG_DIR / "data" / "workflow.db")))
```

```python
# project_workflow/config.py
# Добавить WORKFLOW_DIR через env или fallback рядом с пакетом
PKG_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = os.getenv("WORKFLOW_DIR", str(PKG_DIR / "data"))
```

**Шаг 3: Адаптация conftest**

```python
# tests/conftest.py — monkeypatch уже работает через DB_PATH,
# но надо убедиться что tmp_path fixture не конфликтует
```

**Шаг 4: Проверка**

```bash
cd /opt/dev/hermes-workspace/project-workflow
python -c "from project_workflow.db import DB_PATH; print(DB_PATH)"
# → /opt/dev/hermes-workspace/project-workflow/data/workflow.db

WORKFLOW_DB_PATH=/tmp/custom.db python -c "from project_workflow.db import DB_PATH; print(DB_PATH)"
# → /tmp/custom.db

pytest tests/test_db_path.py -v
```

**Шаг 5: Commit**

```bash
git add project_workflow/db.py project_workflow/config.py tests/test_db_path.py
git commit -m "fix(db): deterministic DB path — package-local fallback instead of expanduser

Removes os.path.expanduser('~') which resolves differently
under systemd vs Hermes terminal. WORKFLOW_DB_PATH env still
overrides. All processes now see the same SQLite file by default."
```

---

### Задача 2: Fix str→int type mismatch в FOREIGN KEY (wizard.py)

**Objective:** `wizard.py` передаёт `phase.code` (str) в `phase_id` (INTEGER FK). Исправить на `phase.id` (int).

**Файлы:**
- Модифицировать: `project_workflow/wizard.py:357-400` (_record_transition, _record_parallel_transition)
- Модифицировать: `project_workflow/wizard.py:657-660` (evaluate_llm create_supervisor_run)
- Создать тест: `tests/test_wizard_fk_types.py`

**Шаг 1: Тест — catch type mismatch**

```python
# tests/test_wizard_fk_types.py
from unittest.mock import patch, MagicMock
from project_workflow.models import Phase
from project_workflow.wizard import WizardEngine

class TestRecordTransitionTypes:
    def test_record_transition_uses_int_phase_id(self):
        engine = WizardEngine("AAT-1", repo="/tmp")
        ph = Phase(id=42, code="1", name="T")
        engine.phase_map = {"1": ph}
        engine.all_phases = [ph]
        engine.current_phase = "1"

        with patch.object(engine.db, "add_task_history") as mock_history, \
             patch.object(engine.db, "update_task") as mock_update:
            engine._record_transition(ph, "pass", "2", None)

        # add_task_history called with int task_id, int phase_id, str status
        call = mock_history.call_args_list[0]
        assert isinstance(call[0][1], int), f"phase_id must be int, got {type(call[0][1])}"
        assert call[0][1] == 42
```

**Шаг 2: Исправление в _record_transition**

```python
# project_workflow/wizard.py
# Заменить phase.code → phase.id во всех add_task_history
self.db.add_task_history(task_id, phase.id, "done")
self.db.add_task_history(task_id, next_phase, "pending")  # next_phase — тоже str! Исправить
```

Но `next_phase` — это code (str), а `add_task_history` ожидает phase_id (int). Нужно резолвить `next_phase` code → int.

```python
# Добавить resolve helper
next_phase_id = None
if next_phase:
    next_phase_obj = self.phase_map.get(next_phase)
    next_phase_id = next_phase_obj.id if next_phase_obj else self.db._resolve_phase_id(next_phase)

self.db.add_task_history(task_id, phase.id, "done")
if next_phase_id:
    self.db.add_task_history(task_id, next_phase_id, "pending")
```

**Шаг 3: Исправление в evaluate_llm**

```python
# wizard.py:657
"phase_id": phase.id,  # вместо phase.code
```

**Шаг 4: Проверка**

```bash
pytest tests/test_wizard_fk_types.py -v
pytest tests/test_wizard.py -v
```

**Шаг 5: Commit**

```bash
git add project_workflow/wizard.py tests/test_wizard_fk_types.py
git commit -m "fix(wizard): use int phase.id for FOREIGN KEY in task_history and supervisor_runs

phase.code (str) was being written into INTEGER NOT NULL phase_id
FK columns. SQLite accepted it silently but this is a schema violation.
Now uses phase.id everywhere."
```

---

### Задача 3: Fix test isolation (флак wizard_coverage)

**Objective:** `test_single_keyword_needs_one_hit` падает при полном прогоне из-за shared DB state. Убедиться что conftest полностью изолирует все тесты wizard.

**Файлы:**
- Модифицировать: `tests/conftest.py`
- Модифицировать: `tests/test_wizard_coverage.py` (убрать прямое создание WorkflowDB без fixture)

**Шаг 1: Аудит conftest**

```python
# conftest.py уже monkeypatch'ит DB_PATH, но test_wizard_coverage.py::TestCheckCoverageEdgeCases
# вызывает self._make_engine() который создаёт WizardEngine("AAT-1") без isolation.
# WizardEngine.__init__ вызывает self.db.init() + schema.ensure_phase_catalog() —
# это трогает monkeypatch'нутый DB_PATH, но concurrent тесты могут конфликтовать
# если несколько WizardEngine инстансов создаются одновременно.
```

Причина флака: несколько тестовых классов используют одинаковый task_key "AAT-1" и пишут в одну и ту же БД. Нужно либо:
а) Использовать разные task_key'и в каждом тесте
б) Очистку таблиц перед каждым тестом

**Шаг 2: Добавить cleanup fixture**

```python
# tests/conftest.py
@pytest.fixture(autouse=True)
def clean_test_db(isolate_ui_runtime_state):
    """Truncate runtime tables between tests to prevent cross-test contamination."""
    wdb = db_module.WorkflowDB()
    wdb.init()
    with wdb._conn() as conn:
        for table in ("supervisor_runs", "task_history", "tasks"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    yield
```

**Шаг 3: Проверка**

```bash
pytest tests/test_wizard_coverage.py -v
pytest -q  # полный прогон, должен быть 0 failures
```

**Шаг 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test: isolate wizard tests — truncate runtime tables between runs

Fixes flaky test_single_keyword_needs_one_hit caused by shared
task_key 'AAT-1' across test classes writing into same DB."
```

---

## Фаза 2: Архитектурный рефакторинг (dual-state remediation)

### Задача 4: CLI step — создавать задачу через DB, не через state.create_task_dir()

**Objective:** Убрать зависимость `cli/ui.py` от `state.find_repo()` и `state.create_task_dir()`. WizardEngine сам создаёт задачу в БД при первом вызове.

**Файлы:**
- Модифицировать: `project_workflow/cli/ui.py:49-91` (step_cmd)
- Модифицировать: `project_workflow/wizard.py:117-142` (_ensure_task)
- Удалить из cli/ui.py: импорты state, find_repo, load_state, create_task_dir

**Шаг 1: Тест — step создаёт задачу без state**

```python
# tests/test_cli_ui.py
def test_step_creates_task_in_db_without_state_files():
    """step --task NEW-KEY должен создать задачу в БД без info/ файлов."""
    from click.testing import CliRunner
    from project_workflow.cli.ui import step_cmd
    from project_workflow.db import WorkflowDB

    runner = CliRunner()
    result = runner.invoke(step_cmd, ["--task", "TASKNEIROKLYUCH-99999"])

    wdb = WorkflowDB()
    task = wdb.get_task_by_key("TASKNEIROKLYUCH-99999")
    assert task is not None
    assert task["current_phase"] != ""
    # Не должно быть info/ файлов
    assert not any(Path(".").rglob("info/sprint*/"))
```

**Шаг 2: Рефактор step_cmd**

```python
# project_workflow/cli/ui.py
# Убрать: from .. import state
# Убрать: found_repo = state.find_repo(task_key)
# Убрать: current = state.load_state(...)
# Убрать: state.create_task_dir(...)

# Новый flow:
# 1. Валидировать task_key
# 2. WizardEngine(task_key, repo=os.getcwd()) — сам создаёт задачу в DB
# 3. Если --report: evaluate → format_result
# 4. Иначе: get_phase_prompt

@cli.command()
@click.option("--task", required=True)
@click.option("--report", default=None)
@click.pass_context
def step_cmd(ctx, task, report):
    task_key = _require_valid_key(task)
    jmode = ctx.obj.get("json_mode", False)
    repo = os.getcwd()

    engine = wizard.WizardEngine(task_key, repo)
    # WizardEngine.__init__ → _ensure_task() уже создаёт/ищет задачу в DB

    if report:
        result = engine.evaluate(report)
        if jmode:
            out_json(result)
        else:
            print(wizard.format_result(result))
        sys.exit(0 if result["verdict"] == "PASS" else 1)

    print(engine.get_phase_prompt())
```

**Шаг 3: Убедиться что _ensure_task работает без repo**

WizardEngine._ensure_task уже создаёт задачу в БД при отсутствии. Нужно проверить что `project` резолвится через `match_project_for_task_key`.

**Шаг 4: Проверка**

```bash
pytest tests/test_cli_ui.py::test_step_creates_task_in_db_without_state_files -v
# + полный прогон CLI тестов
pytest tests/test_cli_*.py -v
```

**Шаг 5: Commit**

```bash
git add project_workflow/cli/ui.py tests/test_cli_ui.py
git commit -m "refactor(cli): step creates task via DB only — remove state.py dependency

Removes state.find_repo, state.load_state, state.create_task_dir from
step command. WizardEngine._ensure_task() handles task creation in DB.
No more info/ directory auto-creation."
```

---

### Задача 5: Удалить мёртвые функции из state.py (или весь файл)

**Objective:** state.py содержит функции, которые больше не используются CLI. Удалить их, оставив только то что реально нужно.

**Файлы:**
- Модифицировать: `project_workflow/state.py`
- Модифицировать: `tests/test_state.py` — либо удалить, либо обновить на DB-only tests

**Шаг 1: Аудит использования state.py**

```bash
cd /opt/dev/hermes-workspace/project-workflow
grep -rn "from.*state import\|import.*state\|state\." project_workflow/cli/ project_workflow/ui.py
```

**Шаг 2: Удалить неиспользуемые функции**

Если после Задачи 4 state.py нигде не импортируется — удалить весь файл.
Если ещё где-то используется — удалить только `create_task_dir`, `find_repo`, `generate_progress_json`.

**Шаг 3: Обновить тесты**

```bash
# Если state.py удалён полностью:
rm tests/test_state.py
# Или переписать на тестирование DB-функций
```

**Шаг 4: Проверка**

```bash
pytest -q
```

**Шаг 5: Commit**

```bash
git add -A
git commit -m "refactor(state): remove file-based state management — DB is sole source of truth

Removes create_task_dir, find_repo, generate_progress_json, progress.json,
and state/*.json files. All task lifecycle handled by WorkflowDB."
```

---

### Задача 6: Удалить verify.py или сделать его опционным

**Objective:** verify.py проверяет JIRA tokens и git identity, но CLI не ходит в Jira. Сделать эти проверки no-op или удалить.

**Файлы:**
- Модифицировать: `project_workflow/verify.py`
- Модифицировать: `tests/test_verify.py`

**Шаг 1: Тест на graceful degradation**

```python
# tests/test_verify.py
def test_check_tokens_returns_unconfigured_gracefully():
    """При отсутствии JIRA env vars verify не должен падать."""
    with patch.dict(os.environ, {}, clear=True):
        ok, msg = verify.check_tokens()
        # Должно быть False но без exception
        assert not ok
        assert "JIRA" in msg
```

**Шаг 2: Убрать жёсткие зависимости**

```python
# verify.py — сделать все функции optional / no-op
# или пометить @deprecated
```

Если verify.py нигде не вызывается из CLI/UI — удалить файл и тест.

**Шаг 3: Проверка**

```bash
pytest tests/test_verify.py -v
```

**Шаг 4: Commit**

```bash
git add project_workflow/verify.py tests/test_verify.py
git commit -m "refactor(verify): make JIRA checks optional — CLI doesn't call Jira API

Removes hard dependency on JIRA_ACCESS_TOKEN and GLAB_TOKEN.
These checks are legacy; actual workflow uses DB-only supervisor."
```

---

## Фаза 3: Cleanup (мусор, dead code, hardcoded config)

### Задача 7: Убрать мусор из репозитория

**Objective:** Удалить `__pycache__/`, `.coverage`, `.workflow.db`, `hello_world.py`, `test_hello.py`. Убедиться что `.gitignore` их блокирует.

**Файлы:**
- Удалить: `project_workflow/__pycache__/` (весь каталог)
- Удалить: `project_workflow/cli/__pycache__/` (весь каталог)
- Удалить: `.coverage`
- Удалить: `.workflow.db`
- Удалить: `hello_world.py`
- Удалить: `test_hello.py`
- Проверить: `.gitignore`

**Шаг 1: Проверить что .gitignore уже покрывает**

```bash
cat .gitignore | grep -E "__pycache__|\.coverage|\.workflow\.db|hello_world"
```

Уже есть `__pycache__/`, `.coverage`, `.workflow.db`. Но файлы всё равно в репозитории (закоммичены ранее).

**Шаг 2: Удалить из git и файловой системы**

```bash
git rm -rf project_workflow/__pycache__ project_workflow/cli/__pycache__
git rm .coverage .workflow.db hello_world.py test_hello.py
```

**Шаг 3: Commit**

```bash
git commit -m "chore: remove committed artifacts — pycache, coverage, db, temp files

These should have been ignored by .gitignore but were committed
before the ignore rules."
```

---

### Задача 8: Убрать мусор из get_phase_prompt()

**Objective:** При `step --task X` (без --report) метод get_phase_prompt() выводит `workflow_lines`, `global_instructions`, `Формат отчёта` — всё это мусор для агента. Оставить только контракт текущей фазы.

**Файлы:**
- Модифицировать: `project_workflow/wizard.py:428-496`
- Модифицировать: `tests/test_wizard.py` (test_get_phase_prompt)

**Шаг 1: Тест на чистоту вывода**

```python
# tests/test_wizard_prompt.py
def test_phase_prompt_has_no_boilerplate():
    engine = WizardEngine("AAT-1", repo="/tmp")
    # ... setup phase ...
    prompt = engine.get_phase_prompt()
    assert "Полный путь workflow" not in prompt
    assert "Правила supervisor" not in prompt
    assert "Формат отчёта" not in prompt
    assert "Контракт текущей фазы" in prompt
    assert "Инструкции" in prompt
    assert "Checks" in prompt
    assert "Evidence" in prompt
```

**Шаг 2: Удалить секции из get_phase_prompt**

```python
# wizard.py
# Удалить:
# - workflow_lines (Полный путь workflow)
# - global_instructions (Правила supervisor)
# - report_lines (Формат отчёта)
# Оставить:
# - Задача, Repo, Workflow, Текущий шаг, CLI entrypoint
# - Контракт текущей фазы (description, execution_type, parallel_with, rollback, next)
# - Инструкции
# - Checks
# - Evidence
# - Delegated banner (если есть)
```

**Шаг 3: Проверка**

```bash
pytest tests/test_wizard_prompt.py -v
pytest tests/test_wizard.py -v
```

**Шаг 4: Commit**

```bash
git add project_workflow/wizard.py tests/test_wizard_prompt.py
git commit -m "refactor(wizard): remove boilerplate from get_phase_prompt output

Removes workflow_lines, global_instructions, and report template
from the phase prompt. Agent only needs current contract + instructions
+ checks + evidence."
```

---

### Задача 9: Вынести hardcoded config в env vars

**Objective:** `config.py` содержит хардкод: SUITES_DIR, GITLAB_PROJECT_ID, JIRA_BASE_URL, VERIFY_SUITE_SCRIPT. Вынести в env с осмысленными дефолтами.

**Файлы:**
- Модифицировать: `project_workflow/config.py`
- Создать: `.env.example`

**Шаг 1: Тест на env override**

```python
# tests/test_config.py
def test_config_reads_from_env():
    with patch.dict(os.environ, {"JIRA_BASE_URL": "https://custom.example.com"}):
        import importlib
        from project_workflow import config
        importlib.reload(config)
        assert config.JIRA_BASE_URL == "https://custom.example.com"
```

**Шаг 2: Рефактор config.py**

```python
# project_workflow/config.py
# Было:
SUITES_DIR = "/root/.hermes/skills/software-development"
# Стало:
SUITES_DIR = os.getenv("WORKFLOW_SUITES_DIR", str(Path.home() / ".hermes" / "skills" / "software-development"))

# Было:
JIRA_BASE_URL = "https://task.wemakedev.ru"
# Стало:
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://task.wemakedev.ru")

# Было:
GITLAB_PROJECT_ID = "73"
# Стало:
GITLAB_PROJECT_ID = os.getenv("GITLAB_PROJECT_ID", "73")

# VERIFY_SUITE_SCRIPT — строить динамически из SUITES_DIR
```

**Шаг 3: Commit**

```bash
git add project_workflow/config.py tests/test_config.py .env.example
git commit -m "refactor(config): move hardcoded URLs and paths to env vars

SUITES_DIR, JIRA_BASE_URL, GITLAB_PROJECT_ID now read from env with
sensible defaults. Allows per-environment configuration without code changes."
```

---

### Задача 10: Убрать dead fields из models.py или добавить в schema

**Objective:** `PhaseCheck.type`, `.command`, `.path`, `.expected`, `.fail_msg`, `.optional` — есть в модели, но в БД нет этих колонок. Либо удалить из модели, либо добавить в schema.

**Решение:** Удалить из модели — они не используются. `PhaseInstruction.example` — тоже удалить.

**Файлы:**
- Модифицировать: `project_workflow/models.py`

**Шаг 1: Упростить PhaseCheck**

```python
# project_workflow/models.py
@dataclass
class PhaseCheck:
    description: str = ""
```

**Шаг 2: Упростить PhaseInstruction**

```python
@dataclass
class PhaseInstruction:
    step: str = ""
    execution_type: str = "sync"
    skills: List[str] = field(default_factory=list)
```

**Шаг 3: Убрать PhaseEvidence.item → использовать description для consistency**

```python
@dataclass
class PhaseEvidence:
    description: str = ""  # вместо item
```

**Шаг 4: Обновить все использования**

```bash
grep -rn "\.item\b" project_workflow/ --include='*.py'
grep -rn "\.example\b" project_workflow/ --include='*.py'
```

Обновить `schema.py`, `wizard.py`, `wizard_contracts.py` чтобы использовать `.description` вместо `.item`.

**Шаг 5: Проверка**

```bash
pytest -q
```

**Шаг 6: Commit**

```bash
git add project_workflow/models.py project_workflow/schema.py project_workflow/wizard*.py
git commit -m "refactor(models): remove dead fields from PhaseCheck/PhaseEvidence/PhaseInstruction

Removes unused fields (.type, .command, .path, .expected, .fail_msg,
.optional from PhaseCheck; .example from PhaseInstruction; .item from
PhaseEvidence). Aligns dataclass with actual DB schema."
```

---

## Фаза 4: Polish

### Задача 11: README актуализация

**Objective:** README.md всё ещё упоминает `python -m project_workflow.ui` для запуска UI. Добавить примечание про systemd. Убрать упоминания `info/` и `progress.json`.

**Файлы:**
- Модифицировать: `README.md`

**Изменения:**
- Web UI запуск: добавить "Production: systemctl restart workflow-ui.service"
- Убрать упоминание info/ директорий
- Убрать упоминание progress.json
- Уточнить что verify-suite.sh опционален

**Commit:**

```bash
git add README.md
git commit -m "docs(readme): update for DB-only state, systemd UI, optional verify"
```

---

## Итоговый чек-лист

- [ ] Задача 1: DB path determinism (hotfix)
- [ ] Задача 2: FK type mismatch fix (hotfix)
- [ ] Задача 3: Test isolation (hotfix)
- [ ] Задача 4: CLI step DB-only creation
- [ ] Задача 5: Remove state.py dead code
- [ ] Задача 6: Make verify.py optional/remove
- [ ] Задача 7: Git cleanup (pycache, .coverage, .workflow.db, temp files)
- [ ] Задача 8: Clean get_phase_prompt()
- [ ] Задача 9: Env-based config
- [ ] Задача 10: Dead fields in models.py
- [ ] Задача 11: README актуализация
- [ ] Полный прогон тестов: `pytest -q` → 0 failures
- [ ] Проверка UI: `curl -s http://localhost:8811/api/tasks`

---

## Оценка трудоёмкости

| Фаза | Задачи | Оценка |
|---|---|---|
| 1 — Hotfixes | 3 | 4-6 часов |
| 2 — Dual-state | 3 | 6-8 часов |
| 3 — Cleanup | 4 | 4-6 часов |
| 4 — Polish | 1 | 1-2 часа |
| **Итого** | **11** | **15-22 часа** |

**Приоритет:** Фаза 1 критическая — делать первой. Фаза 2 архитектурная — без неё debt растёт. Фазы 3-4 можно параллелизировать после завершения 1-2.
