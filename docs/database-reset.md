# Сброс базы project-workflow

Этот runbook предназначен для оператора, который обновляет окружение на версию с
baseline migration `0001_initial`.

Любая база с revision, отличной от `0001_initial`, несовместима с этой версией.
После необходимого внешнего backup её настроенную schema или Compose volume нужно
удалить полностью; upgrade, stamp и импорт прежних данных не поддерживаются.

> **Внимание:** операции ниже безвозвратно удаляют все данные project-workflow в
> выбранной схеме или Compose volume. Автоматический импорт старых данных не
> поддерживается. Сначала сделайте внешний backup, если данные могут понадобиться.

## Перед сбросом

1. Зафиксируйте окружение, `DATABASE_URL`, `DB_SCHEMA` и текущий commit приложения.
2. Убедитесь, что `DB_SCHEMA` указывает только на схему project-workflow. Не
   выполняйте команды для `public` или общей схемы.
3. При необходимости сохраните backup вне контейнера:

   ```bash
   pg_dump --format=custom --schema=project_workflow \
     --file=project-workflow-before-reset.dump "$DATABASE_URL"
   ```

4. Остановите API и активных CLI-исполнителей, чтобы они не писали в БД во время
   сброса.

## Сброс только настроенной схемы

Для стандартного Compose-окружения:

```bash
docker compose stop api
docker compose exec -T db psql \
  -U project_workflow -d project_workflow -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA IF EXISTS project_workflow CASCADE;'
docker compose run --rm migrate
docker compose up -d api
```

Для внешнего PostgreSQL выполните эквивалентный `DROP SCHEMA` только после
проверки точного endpoint и имени схемы. Не используйте `alembic stamp` и не
пытайтесь обновить прежнюю revision.

## Сброс Compose volume

Этот вариант удаляет весь локальный PostgreSQL volume текущего Compose project.
Перед выполнением проверьте имя project и список volumes:

```bash
docker compose ls
docker compose config --volumes
docker compose down --volumes
docker compose up --build -d
```

В текущем Compose определён один volume `postgres_data`. Если конфигурация была
расширена, не используйте `--volumes`, пока не проверите каждый удаляемый volume.

## Проверка после сброса

```bash
docker compose ps
docker compose logs --no-log-prefix migrate
curl --fail --silent http://127.0.0.1:8812/health
```

Успешный результат:

- сервис `migrate` завершился с exit code `0`;
- API запущен только после `migrate`;
- `/health` возвращает HTTP `200`, `database=ok` и `schema=ok`;
- в `alembic_version` находится `0001_initial`;
- packaged-каталог, агенты и default project созданы без дубликатов.

PostgreSQL и API в стандартном Compose опубликованы только на `127.0.0.1`.
Для удалённой проверки используйте защищённый proxy или VPN, не меняя host
bindings на общедоступный интерфейс.

Локальные проверки, hosted CI и реальный provider-run фиксируются как разные
классы evidence. Успешный reset сам по себе не подтверждает работу внешнего LLM.
