# Live-приёмка CLI / WizardEngine

## Цель

Проверить полный runtime-путь без подмены Wizard или LLM-клиента:

```text
CLI subprocess -> PostgreSQL -> OpenAI-compatible HTTP -> WizardEngine -> PostgreSQL
```

Каталог по умолчанию содержит 27 фаз и требует 22 обращения к evaluator. Параллельные группы:

- `0.6 + 1`;
- `1.5 + 2`;
- `4.5 + 5`;
- `7.5 + 7.6 + 7.6.R`.

## Автоматическая приёмка

Для интеграционных тестов нужна отдельная PostgreSQL, указанная через стандартные
`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`.

```bash
pytest -q --timeout=60
pytest -q -m integration tests/test_postgres_integration.py --timeout=180
pytest --cov=project_workflow --cov-report=term --timeout=60
ruff check .
mypy project_workflow scripts
git diff --check
python -m project_workflow.interfaces.cli --help
```

Стандартный pytest намеренно исключает тесты с marker `integration`; поэтому они
показываются как `deselected` и обязательно запускаются второй командой.

Актуальный baseline: **804 passed, 12 deselected**, отдельный PostgreSQL suite —
**12 passed**, coverage — **95.23%**. Для integration-набора используется больший
timeout, потому что полный Windows-сценарий последовательно запускает 24 CLI subprocess.

`test_full_default_workflow_through_cli_postgres_and_http` поднимает stdlib HTTP-сервер
с настоящими `/v1/models` и `/v1/chat/completions`, запускает CLI отдельными процессами
и проверяет 27 завершённых фаз, 22 supervisor run, fingerprints, audit и replay.

`test_cli_verdicts_replay_and_fail_closed_through_postgres_and_http` отдельно проверяет
`PARTIAL`, `BLOCKED`, `ROLLBACK`, `DELEGATE`, invalid JSON, HTTP error и exit codes.
Миграционные проверки также подтверждают преобразование `soft_fail → partial`,
`hard_fail → blocked`, новый constraint только для пяти актуальных verdict и безопасное
обновление seed-managed каталога без изменения ID задач и audit-записей.

## Реальная проверка Ollama Online

Эта проверка выполняется только после автоматического suite и только на явно выбранной
локальной тестовой PostgreSQL. Relevanter Dev, SSH и deploy не используются.

1. Убедиться, что `DATABASE_URL` указывает на `localhost`/`127.0.0.1` и не содержит адрес
   Relevanter Dev.
2. Не очищать и не пересоздавать общую локальную БД. Выполнить `python scripts/init_db.py`:
   миграции и bootstrap идемпотентны.
3. Проверить каталог: ровно 27 фаз, `phase_order` равен `1..27`, а четыре параллельные
   группы совпадают со списком выше. При расхождении остановиться без записи.
4. Настроить `OPENAI_API_KEY`; значения по умолчанию — `OPENAI_BASE_URL=https://ollama.com/v1`,
   `OPENAI_MODEL=qwen3.5:397b` и `OPENAI_REASONING_EFFORT=none`. Проверить `/v1/models`, не выводя ключ.
5. Создать новый ключ `TASK-<timestamp>` и через `project-workflow --json step` подать
   22 полных отчёта по ID checks/evidence текущего контракта.
6. После отчёта для `0.6 + 1` убедиться, что текущая группа — `1.5 + 2`, а эти фазы ещё
   не завершены. После следующего отчёта задача должна перейти на фазу `3`.
7. Финально проверить `phase=10`, `status=done`, 27 завершённых записей истории фаз,
   22 supervisor run и fingerprint, а также model, endpoint mode, prompt version и raw
   evaluator в audit snapshot.
8. Повтор первого отчёта должен вернуть `replayed=true` без нового вызова provider и
   без дополнительного перехода.

Любой неожиданный `PARTIAL/BLOCKED`, неверная граница группы или provider error означает
провал live-приёмки. Fallback и принудительное продвижение не используются. Тестовую
задачу оставляют в локальной БД для просмотра истории; временные логи не коммитят.
