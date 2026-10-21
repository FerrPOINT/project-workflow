# Итоговый Base UI и Workflow: 21 октября 2026

Workflow получает общие SSR-контракты Base #298 и layout из #297 через
независимый UI pin `633ebc146553a64e5cad4d8f179aec63c741d04c`
(детерминированный exporter из Base #301). SDK, skills, dependency lock, API, миграции и Python
исполнение не меняются. Runtime не устанавливался; использовалась собственная
нейтральная SQLite smoke-база, удалённая после остановки временного процесса.

## Локальная проверка

- 246 UI/branding/prefix/fixture tests PASS; ruff PASS; mypy:142 файлов PASS.
- 13 documentation tests и 9 Node navigation tests PASS.
- Chromium:320/375/767/768/1000/1279/1280/1920/2560 px, оба selector,
  Back/Forward/reload, клавиатура, popup и mobile drawer PASS.
- На собственной записи выполнены create/edit/delete workflow, failed-save
  с сохранением черновика, очистка foreign mode и сохранение profession/project
  scope. Дополнительно проверены границы picker980/981 px и единая кнопка
  редактирования; удаление собственной профессии сохранило соседние fixtures.
- Получены17 скриншотов полного нейтрального каталога. Просмотрены
  [форма профессии](../screenshots/branding-pin-convergence-20261021/profession-desktop.png)
  и [mobile settings](../screenshots/branding-pin-convergence-20261021/settings-mobile.png).

Smoke runners обновлены на действующие контракты: общий platform mark,
canonical UI profession_id (API namespace_id сохранён), rail72 px вместо
старых60 px, видимые Base Select triggers и одна responsive edit action.
До исправления runners падали на старых selectors/ожиданиях; assertions
приведены к проверенным Base/product contracts, production CSS не переопределён.

## Полный hosted gate и граница повторного использования

Run39561495321 на b04cb644fbd45aa1089e16d6fff74c2968263e60 завершился PASS:
3084 unit/UI tests,60 subtests,5 optional skips,112 PostgreSQL cases,
coverage94.22%, Node navigation,ruff,mypy,docs и Compose smoke.

Этот полный результат относится к указанному input. Финальный input дополнен
UI pin и QA/docs; его production Python/dependencies/SDK и22 канонических SSR
assets совпадают с квалифицированным b04. Новый exporter исправляет только
порядок font-ключей fingerprint; проверяется штатный --check и каждый raw SHA.
Повторное выполнение полного backend/PG gate для QA runner не заявляется.
