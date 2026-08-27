<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=180&text=project-workflow&desc=State-driven%20workflow%20platform&fontColor=F8FAFC&fontSize=60&fontAlignY=35&descAlignY=55&color=06B6D4" alt="project-workflow banner" />
</p>

<p align="center">
  <a href="#features"><img src="https://img.shields.io/badge/%E2%9C%A8%20Features-0B1220?style=for-the-badge" /></a>
  <a href="#stack"><img src="https://img.shields.io/badge/%F0%9F%94%A7%20Stack-111827?style=for-the-badge" /></a>
  <a href="#cli"><img src="https://img.shields.io/badge/%F0%9F%96%A5%EF%B8%8F%20CLI-1F2937?style=for-the-badge" /></a>
  <a href="#ui"><img src="https://img.shields.io/badge/%F0%9F%8C%90%20Web%20UI-374151?style=for-the-badge" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/%F0%9F%8F%97%EF%B8%8F%20Architecture-4B5563?style=for-the-badge" /></a>
  <a href="#quality"><img src="https://img.shields.io/badge/%F0%9F%9B%A1%EF%B8%8F%20Quality-6B7280?style=for-the-badge" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Postgres-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="Postgres" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/uv-000000?style=flat-square&logo=astral&logoColor=white" alt="uv" />
  <img src="https://img.shields.io/badge/Rich-000000?style=flat-square&logo=rich&logoColor=white" alt="Rich" />
  <img src="https://img.shields.io/badge/Jinja2-B41717?style=flat-square&logo=jinja&logoColor=white" alt="Jinja2" />
  <img src="https://img.shields.io/badge/Alembic-6B8E23?style=flat-square&logo=alembic&logoColor=white" alt="Alembic" />
  <img src="https://img.shields.io/badge/OpenAI%20Compatible-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI Compatible" />
  <img src="https://img.shields.io/badge/LiteLLM-app--test-5B5BD6?style=flat-square" alt="LiteLLM app-test" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" alt="pytest" />
  <img src="https://img.shields.io/badge/ruff-261230?style=flat-square&logo=ruff&logoColor=white" alt="ruff" />
  <img src="https://img.shields.io/badge/mypy-2E6AFF?style=flat-square&logo=mypy&logoColor=white" alt="mypy" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License MIT" />
</p>

---

## Позиционирование

Пофазовый движок управления задачами.
Агент отчитывается через CLI, обязательный LLM-supervisor оценивает отчёт и выдаёт вердикт: **PASS**, **PARTIAL**, **ROLLBACK**, **BLOCKED** или **DELEGATE**.
Всё управление шаблонами workflow, фазами, проектами, агентами и задачами ведётся через Web UI.

CLI остаётся минимальным: ровно две команды — `step` и `history`.

В рабочем runtime используется **PostgreSQL**.

SQLite остаётся только для изолированных тестов с явно заданным DSN/engine.

<a name="features"></a>
## ✨ Возможности

| Возможность | Описание |
|---------|----------|
| Пофазовый workflow | Каждая задача строго следует шаблону фаз с инструкциями, чек-листами и артефактами. |
| Рекомендации skills | Имена skills хранятся в PostgreSQL и передаются исполнителю прямо в контракте фазы; содержимое принадлежит [`relevanter/agent-skills`](https://gt.wmtgroup.ru/relevanter/agent-skills). |
| Hermes profiles | Агенту можно назначить уникальное имя Hermes-профиля; Supervisor передаёт его исполнителю вместе с заданием. |
| Встроенный supervisor | Автоматическая оценка отчётов и решение о переходе на следующую фазу. |
| Web UI | Управление шаблонами, фазами, проектами, задачами и агентами через браузер. |
| CLI freeze | Только `step` и `history`; весь CRUD — через UI. |
| PostgreSQL | Единый runtime: UI и CLI используют тот же Postgres через `DATABASE_URL`. |
| Автоматические миграции | `docker compose up` сам создаёт схему, таблицы и baseline. |

<a name="stack"></a>
## 🔧 Стек

| Зона | Технология | Роль |
|------|------|------|
| Runtime | Python 3.11 | основной язык |
| Данные | PostgreSQL | runtime БД |
| ORM & migrations | SQLAlchemy 2 + Alembic | модели, репозитории, UoW, миграции |
| API | FastAPI + Pydantic | UI и JSON API |
| UI | Jinja2 + minimal JS | server-side HTML, без frontend-фреймворков |
| LLM / Supervisor | OpenAI-compatible Chat Completions | единственный evaluator отчётов; Octo LiteLLM `app-test`, без fallback |
| CLI | Click + Rich | `step` / `history` |
| Config | Pydantic Settings | `.env`, переменные окружения |

<a name="cli"></a>
## 🖥️ CLI

```bash
# Выполнить текущую фазу задачи и получить вердикт supervisor
project-workflow step --task RUN-123 --report "Сделал X, проверил Y"

# История отчётов step и ответов Supervisor
project-workflow history --task RUN-123 --n 10
```

CLI ожидает `DATABASE_URL` и доступный OpenAI-compatible evaluator. Каноническая конфигурация использует OpenRouter:

```bash
export DATABASE_URL=postgresql+psycopg://project_workflow:project_workflow@localhost/project_workflow
export OPENAI_BASE_URL=http://192.168.10.1:4000/v1
export OPENAI_MODEL=app-test
export OPENAI_TIMEOUT=120
export OPENAI_API_KEY=<litellm-master-key>
export OPENAI_REASONING_EFFORT=none
```

Если endpoint не поддерживает `reasoning_effort`, задайте `OPENAI_REASONING_EFFORT=`.

Fallback evaluator отсутствует: если провайдер недоступен или вернул некорректный JSON, задача остаётся на текущей фазе, атомарно получает `status=blocked`, событие `blocked` и запись `task_step_history` без fingerprint; команда возвращает retryable `BLOCKED` и exit code `1`. Повтор снова вызывает provider, а успешная оценка снимает техническую блокировку обычным переходом.
Для стандартного OpenRouter непустой `OPENAI_API_KEY` обязателен: без него Supervisor блокирует переход локально и не выполняет заведомо неуспешный внешний запрос. Пользовательский OpenAI-compatible endpoint может работать без ключа, если это допускает сам endpoint.
Ответ evaluator принимается только по точному JSON-контракту: uppercase verdict, обязательные `message` и finite `confidence` в диапазоне `0..1`, непустые строковые элементы массивов и отсутствие неизвестных полей. Replay действует только для той же задачи, фазы, нормализованного отчёта и неизменившегося contract fingerprint. DB-транзакция не удерживается во время provider-вызова; изменение каталога до применения verdict даёт retryable `BLOCKED` без fingerprint.
Повторный отчёт после `status=done` не вызывает evaluator и не создаёт новые записи: CLI возвращает `PASS`, `status=done` и `next_phase_code=null`.

Команда `step` возвращает текущий snapshot задачи и, после оценки, одной транзакцией сохраняет пару «отчёт исполнителя → ответ Supervisor» в `task_step_history`, связанные события перехода в `task_phase_events` и новое текущее состояние в `tasks`. Команда `history` читает только `task_step_history` и показывает отчёт, verdict, сообщение Supervisor, оценённую/следующую/rollback-фазу и время; timeline UI строится отдельно по `task_phase_events`.

<a name="ui"></a>
## 🌐 Web UI

Поддерживаемый локальный запуск Web UI выполняется через Docker Compose:

```bash
cp .env.example .env
docker compose up --build -d --wait
# UI доступен на http://127.0.0.1:8812
```

Перед первым запуском `scripts/init_db.py` применяет единственную baseline migration
`0001_initial`, загружает packaged-каталог и создаёт default project. Повторный запуск
идемпотентен и не перезаписывает изменения из UI.

Старые Alembic revision намеренно не поддерживаются. При обнаружении прежней или
неверсионированной схемы инициализация завершается сообщением
«Несовместимую базу данных необходимо пересоздать»; автоматические `drop` и `stamp` не выполняются.
Перед запуском новой версии существующую схему или Compose volume нужно явно
пересоздать по [reset-runbook](docs/database-reset.md). Импорт прежних данных не предусмотрен.

В Compose схема и каталог создаются отдельным сервисом `migrate`; API стартует только
после его успешного завершения.

Compose публикует PostgreSQL и API только на `127.0.0.1`. Удалённый доступ
разрешён только через отдельно настроенный защищённый proxy или VPN; прямую
публикацию портов во внешнюю сеть этот репозиторий не поддерживает.

### Hermes-профили агентов

На странице «Агенты» можно связать workflow-агента с уже существующим профилем
Hermes. В базе хранится только непрозрачное имя профиля, например
`review_profile`; ключи, skills, память и конфигурация остаются в Hermes.
Один профиль нельзя назначить двум агентам, чтобы два исполнителя не писали в
один `HERMES_HOME` одновременно.

Внешний исполнитель получает `hermes_profile` в serial- или parallel-контракте
и запускает Hermes канонической командой:

```bash
hermes --profile review_profile --oneshot "<phase prompt>"
```

Supervisor не проверяет наличие профиля и не загружает его содержимое: эта граница
принадлежит executor. Пустое поле означает, что конкретный Hermes-профиль для
агента не задан.

<a name="architecture"></a>
## 🏗️ Architecture

```mermaid
flowchart TD
    CLI[CLI project-workflow] -->|step / history| WE[SupervisorEngine]
    UI[Web UI FastAPI+Jinja2] -->|CRUD / HTML| API[API routes]
    API -->|UoW| Repo[SQLAlchemy Repositories]
    WE --> Repo
    Repo --> DB[(PostgreSQL)]
    WE --> SV[Supervisor / LLM checks]
    SV -->|verdict| WE
    Seed[packaged seed, empty DB only] --> DB
```

### Схема состояния и истории

```mermaid
erDiagram
    WORKFLOWS ||--o{ PHASES : содержит
    WORKFLOWS ||--o{ PROJECTS : использует
    WORKFLOWS ||--o{ TASKS : определяет
    PROJECTS ||--o{ TASKS : содержит
    PHASES ||--o{ PHASE_INSTRUCTIONS : содержит
    PHASES ||--o{ PHASE_CHECKS : содержит
    PHASES ||--o{ PHASE_EVIDENCE_REQUIREMENTS : требует
    PHASES ||--o{ TASKS : "текущая фаза"
    TASKS ||--o{ TASK_PHASE_EVENTS : журнал
    TASKS ||--o{ TASK_STEP_HISTORY : проверки
    TASK_STEP_HISTORY ||--o{ TASK_PHASE_EVENTS : вызывает
```

`tasks` — единственный текущий snapshot задачи. `task_phase_events` — append-only журнал событий `entered`, `completed`, `blocked`, `resumed` и `rolled_back`. `task_step_history` — история вызовов `step`: отчёт исполнителя, verdict, покрытые и пропущенные пункты, ответ Supervisor, снимок контракта и вычисленные переходы. Отдельная chat-таблица не нужна: одна step-запись хранит законченную пару запроса и ответа.

Создание проекта требует явного положительного `workflow_id`; runtime не создаёт и не выбирает default workflow. Удаление задач через REST, UI, application service или repository не поддерживается: snapshot и связанный audit сохраняются, а FK используют `RESTRICT`. Внутренний `workflow_id` в audit-таблицах служит только для составных FK ownership и не дублируется в публичных DTO.

Каталог физически хранится в `workflows`, `phases`, `phase_instructions`, `phase_checks` и `phase_evidence_requirements`. Ссылки текущей, parallel- и rollback-фаз являются числовыми FK; коды используются только как явные `*_phase_code` в CLI, seed и Supervisor-контракте.

### Принципы

- Единый data layer: все операции через SQLAlchemy-модели и репозитории.
- Единственный evaluator — обязательный OpenAI-compatible LLM.
- UI-пакет (`project_workflow/interfaces/ui/`) — чистое FastAPI-приложение с отдельными routes, services, dependencies.
- Конфигурация централизована в `project_workflow.config` на Pydantic Settings; `DATABASE_URL` обязателен.
- PostgreSQL хранит один редактируемый каталог, snapshot задач, append-only события фаз и историю `step`; packaged JSON seed из 19 фаз используется только при bootstrap пустой БД.
- Граф фаз валидируется целиком до записи: порядок всегда `1..N`, rollback направлен назад, а явные parallel-ссылки соединяют только фазы одного непрерывного parallel-сегмента. Isolated parallel допустим; все фазы связанной parallel-группы используют одну общую цель rollback либо не задают её.
- REST принимает числовые phase resource IDs и строгие JSON-типы; `key_prefixes` — только непустой `list[str]`, а reorder инструкций — полный уникальный набор ID одной фазы. Строковые обходные формы не поддерживаются.
- При полном обновлении фазы каждый вложенный элемент `instructions`, `checks` и `evidence` обязан передать `id`: положительный integer обновляет существующую запись, `null` создаёт новую, отсутствие элемента удаляет его. Неизвестный или принадлежащий другой фазе ID отклоняет всю транзакцию; сохранение без изменений сохраняет ID и replay fingerprint.
- Skills являются рекомендациями внутри инструкций фазы; их канонические файлы хранятся в `relevanter/agent-skills`, отдельного runtime registry нет.
- Hermes profile является уникальной строковой ссылкой на профиль внешнего исполнителя; очистка выполняется только явным `null`. Workflow не копирует конфигурацию или секреты Hermes.

<a name="quality"></a>
## 🛡️ Проверки качества

| Проверка | Команда | Статус |
|---|---|---|
| Lint | `ruff check .` | **green** |
| Type check | `mypy project_workflow scripts` | **без ошибок** |
| Tests | `pytest -q --timeout=60` | **без падений** |
| PostgreSQL integration | `pytest -q -m integration tests/test_postgres_integration.py --timeout=120` | **без падений** |
| Coverage | `pytest --cov=project_workflow --cov-report=term --timeout=60` | **не ниже 90%** |
| Compose readiness | `curl --fail http://127.0.0.1:8812/health` | **200** |

<a name="roadmap"></a>
## 🗺️ Готовность

- [x] Конфигурация на Pydantic Settings (`DATABASE_URL` required)
- [x] SQLAlchemy-модели, репозитории и unit-of-work
- [x] Одна Alembic baseline migration + единый идемпотентный `scripts/init_db.py`
- [x] Docker Compose: Postgres + migrate + UI
- [x] UI/API переведены на SQLAlchemy-сервисы
- [x] Один runtime dataflow: CLI/UI → Supervisor → OpenAI-compatible evaluator → PostgreSQL
- [x] Полный pytest suite и отдельный PostgreSQL integration gate
- [x] Postgres-интеграционные тесты
- [x] `SupervisorEngine` и supervisor-модули собраны в пакет `project_workflow/supervisor/`
- [x] API-тесты на все UI routes
- [x] Runtime hardening: `/health`, корректное завершение и retry подключения к PostgreSQL
- [x] Coverage >= 90%
- [x] mypy `--check-untyped-defs` для supervisor/core.py
- [x] UI-доработки: execution_type на отдельной строке, русское склонение счётчиков, очистка рабочей БД от мусора
- [x] Supervisor evaluate: раздельные `task_phase_events`/`task_step_history`, idempotent replay и явный parallel rendering
- [x] Актуальный packaged Business Tech catalog `sdlc-business-tech-v1` из 19 фаз загружается один раз в пустую PostgreSQL database
- [x] Tech Pull Request contract: Hermes создаёт PR, Maintainer вручную merge, Hermes проверяет SHA и build
- [x] Фазы packaged-каталога связаны с именованными Hermes profiles
- [x] JSON `step` отдаёт полный `phase_contract`, включая `skills`, profile и детали parallel-участников
- [x] Packaged seed загружается только при bootstrap пустой схемы

## Установка

```bash
git clone https://github.com/FerrPOINT/project-workflow.git
cd project-workflow
python -m venv .venv
source .venv/bin/activate
python -m pip install --constraint constraints.txt -e ".[dev,ui]"
```

`constraints.txt` фиксирует единый проверяемый набор версий для Python 3.10 и
3.11. Docker-сборка использует тот же файл, устанавливает приложение в
`/opt/venv` и не переносит глобальный `site-packages` или инструменты сборки в
финальный runtime-слой.

`project-workflow` — самостоятельная внутренняя delivery-утилита, а не product
runtime Relevanter. Актуальный packaged-каталог описывает работу через
Relevanter Business и Relevanter Tech; внешние интеграции остаются во владении
соответствующих исполнителей.

## Лицензия

MIT


