# Реестр post-merge аудита багов

Реестр фиксирует только дефекты существующего `project-workflow`. Новые
продуктовые возможности, compatibility-слои и дополнительные runtime-компоненты
в этот аудит не входят.

## Подтверждённые дефекты

| ID | Аспект | Дефект | Доказательство | Статус |
| --- | --- | --- | --- | --- |
| BUG-001 | SQLite test helper | Обработчик подключения проверял отсутствующий `connection_record.dialect`, поэтому `foreign_keys=0` и `journal_mode=delete`; SQLite-тесты не воспроизводили FK-поведение PostgreSQL. | Регрессия проверяет `PRAGMA foreign_keys=1` и `journal_mode=wal`. | Исправлено в текущей ветке |
| BUG-002 | Web UI / REST | Reorder фаз сериализовал `data-*` как JSON-строку, хотя strict API требует integer; действие из браузера получало `422`. | Template regression проверяет явное числовое преобразование `phase_id`. | Исправлено в текущей ветке |
| BUG-003 | UI / fail-closed | Задача со статусом `blocked` исчезала из списка незавершённых на дашборде, а общий DTO подписывал её как «В работе». | Service regression проверяет видимость blocked-задачи и метку «Заблокирована». | Исправлено в текущей ветке |
| BUG-004 | Локализация | Ошибка удаления единственной фазы и blocker сбоя evaluator возвращались на английском. | API и Supervisor regression tests проверяют русские сообщения. | Исправлено в текущей ветке |
| BUG-005 | UI / cleanup | Карточка задачи всегда показывала «Время в работе —»: у поля не было producer, storage или вычисления. | Caller sweep нашёл только template context и test fixture; template regression запрещает мёртвую метрику. | Исправлено в текущей ветке |
| BUG-006 | PostgreSQL / concurrency | Удаление задачи могло завершиться между повторным чтением Supervisor и записью audit-run, вызывая raw `ForeignKeyViolation`. | PostgreSQL barrier-test воспроизвёл сбой и проверяет сериализацию удаления за workflow/project/task locks. | Исправлено в текущей ветке |
| BUG-007 | Supervisor / agent concurrency | Имя или Hermes-профиль назначенного агента могли измениться после финальной перепроверки контракта, но до commit verdict. | PostgreSQL barrier-test проверяет порядок `agent → workflow` и ожидание commit Supervisor. | Исправлено в текущей ветке |
| BUG-008 | Web UI / errors | Часть CRUD-вызовов не обрабатывала network rejection; удаление задачи вместо ошибки молча перезагружало страницу. | Template regressions проверяют единый русский network feedback для CRUD-страниц и отсутствие reload при отказе. | Исправлено в текущей ветке |
| BUG-009 | Web UI / phase aggregate | Очистка текста существующей check/evidence удаляла строку только из DOM и не сохраняла изменение. | Template regression требует save при empty blur и восстановление удалённого DOM-узла при отказе aggregate update. | Исправлено в текущей ветке |
| BUG-010 | Domain / CLI contract | `TaskService` проверял только префикс и принимал `RUN`, `RUN-RACE` и `RUN-12X`, хотя поддерживаемый CLI требует `PREFIX-<число>`. | Unit regression проверяет общий `TaskKeyValidator`; примеры CLI приведены к `RUN-42`. | Исправлено в текущей ветке |
| BUG-011 | REST / concurrency | `DELETE /api/tasks/{task_key}` не маппил `NotFoundError`/`ConflictError`, которые стали возможны после повторных проверок под locks, и мог вернуть `500`. | Route regression проверяет контролируемые `404` и `409` с безопасным JSON. | Исправлено в текущей ветке |
| BUG-012 | Локализация / diagnostics | Ошибка отсутствующего `DATABASE_URL` и diagnostics повреждённых persisted JSON-полей были на английском и могли попасть в CLI/log diagnostics. | Localization regressions проверяют русские configuration и corruption errors; parser LLM остаётся техническим и скрыт fail-closed от пользователя. | Исправлено в текущей ветке |
| BUG-013 | Strict validation | `InstructionService` превращал строковый `step_num` и `bool` в целое, а reorder принимал `bool` как instruction ID, хотя REST DTO запрещали эти формы. | Service/API regressions проверяют string/float/bool/non-positive IDs и отсутствие записей при отказе. | Исправлено в текущей ветке |
| BUG-014 | Recorder / security | Raw URL/query strings с `access_token`, `refresh_token`, `client_secret`, `private_token` и похожими параметрами не маскировались; exact nested keys тоже были неполными. | Recorder regressions проверяют query/assignment и nested-key redaction, а также safe near-miss (`token_count`, `client_secret_name`). | Исправлено в текущей ветке |
| BUG-015 | Web UI / feedback | После успешной перестановки инструкций toast создавался без типа и получал несуществующий класс `toast-undefined`. | Template regression требует явный тип `success` и запрещает однопараметрический вызов. | Исправлено в текущей ветке |
| BUG-016 | CLI / локализация | Справка CLI и вывод версии оставляли стандартные заголовки и сообщения Click на английском (`Usage`, `Options`, `Commands`, `Show...`, `version`), а описания команд начинались с `Step`/`History`. | CLI regressions проверяют корневую и вложенную справку, сообщение версии и запрещают английские служебные строки. | Исправлено в текущей ветке |
| BUG-017 | Web UI / локализация | Дашборд, список и карточка задачи показывали сырые verdict-коды (`PASS`, `BLOCKED`) вместо русских пользовательских меток. | Service/template regressions проверяют единое отображение verdict; браузерная проверка подтвердила русские метки в реальном UI. | Исправлено в текущей ветке |

## Следующие проверки

- [x] Readiness/bootstrap повторно проверены на лишних и отсутствующих таблицах,
  неверной revision и ошибке seed до первой записи; SQLite-набор и PostgreSQL
  initial migration проходят полностью.
- [x] Caller/legacy sweep подтверждает, что новые `TaskRepository.lock()` и
  `PhaseRepository.workflow_ids_for_agent()` имеют ровно по одному production-consumer,
  а production `create_all` ограничен явным SQLite test helper `ensure_schema()`.
