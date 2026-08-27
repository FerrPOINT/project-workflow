# Обновление базы project-workflow

Этот runbook описывает безопасное обновление PostgreSQL до текущей Alembic
revision. Сброс общей базы и удаление volume не являются штатным способом
обновления.

## Поддерживаемый путь

- пустая PostgreSQL проходит `0001_initial → 0002_sdlc_v2 → 0003_normalized`;
- развёрнутая база на `0002_sdlc_v2` обновляется до `0003_normalized`;
- задачи, workflow, проекты, контракты фаз, evaluator runs и phase history
  сохраняются;
- неизвестная revision, неполная схема или schema drift блокируют запуск без
  автоматического `drop` или `stamp`;
- SQLite создаётся через ORM только для явно переданных изолированных тестовых
  URL и не является runtime-путём миграции.

## Перед обновлением общего окружения

1. Зафиксировать endpoint, `DB_SCHEMA`, текущую revision и SHA образа.
2. Остановить API и CLI-исполнителей, чтобы во время миграции не было записей.
3. Создать внешний backup:

   ```bash
   pg_dump --format=custom --schema=project_workflow \
     --file=project-workflow-before-upgrade.dump "$DATABASE_URL"
   ```

4. Восстановить backup в отдельную тестовую БД и выполнить на ней
   `alembic upgrade head`.
5. Проверить revision, количество задач/history/audit, schema diff и повторный
   `upgrade head`.

## Применение

```bash
python scripts/init_db.py
```

Успешный результат:

- `alembic_version = 0003_normalized`;
- `/health` возвращает HTTP `200`, `database=ok` и `schema=ok`;
- старые задачи открываются, а `history` показывает прежние evaluator runs;
- повторный запуск не меняет данные.

## Откат

Lossless downgrade нормализованного append-only audit не поддерживается.
Откат выполняется возвратом предыдущего образа вместе с восстановлением
предварительного PostgreSQL backup. Нельзя откатывать только приложение поверх
уже обновлённой схемы.
