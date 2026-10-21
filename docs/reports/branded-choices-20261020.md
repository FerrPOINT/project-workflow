# Фирменные поля выбора: корректировки после hosted gate

Дата: 2026-10-20. UI Base закреплён независимо на
`d8ac701675d6d494ad55fc60ff91ae75bf980334`; SDK/skills и установка не меняются.

## Причины и исправления

Первый hosted quality run `39373544809` завершился с 15 failed, 2969 passed,
5 skipped, 96 deselected и 60 passed subtests. Это настоящий failed gate,
не инфраструктурная недоступность и не подтверждение готовности.

- Шесть catalog navigation cases обнаружили настоящую регрессию: перенос
  profession selector убрал выбранный disabled option с пустым ID. В каталоге
  браузер выбирал первую профессию. Пустое состояние «Каталог воркфлоу» восстановлено;
  исходные шесть тестов не менялись и теперь проходят как для связанного,
  так и для независимого workflow, несмотря на cookie другого namespace.
- Два deployment prefix cases извлекали switchNamespace без нового локального
  состояния/refresh. Стенд включает полный причинный фрагмент и DOM query contract;
  проверка сохранения project scope, смены профессии и удаления phase scope сохранена.
- Cookie test проверяет scope всех namespace cookie writers вместо прежнего числа
  дублирующих writers. Проверка отменённой навигации отдельно доказывает сохранение
  confirmed controls и отсутствие преждевременной записи cookie.
- Шесть pending-save cases получили недостающий DOM matches в стенде. Стенд теперь
  проверяет также refresh backing select с состояниями disabled true/false.
  Сохранены проверки единственной записи, блокировки идентичности и ввода при ошибке.

## Адресная проверка

Команда: pytest -q tests/test_catalog_navigation.py tests/test_deployment_prefix.py
 tests/test_sso_cookie_isolation.py tests/test_workflow_pending_save.py
 tests/test_choice_contract.py --timeout=60.

Результат: **33 passed in 2.85s**. Ruff для трёх изменённых Python-файлов PASS;
исправление последующего line-length не меняет исполнение. Повтор полного suite,
coverage или backend build не запускался: изменились один template и тестовые стенды.
Hosted повторяется по новому PR head; его результат учитывается отдельно.

## Незавершённая браузерная проверка

Справочник Base и штатные синтетические Fleet/Forge previews проверены ранее
на точном UI fingerprint. SSR Workflow через IAB ещё не принят. Запуск отдельного
HTTP-стенда поверх изолированного SQLite test fixture был отклонён автоматической
проверкой с ответом `blocked by policy` без дополнительной причины; команда не исполнилась.
Запрет не обходился. Нужен доступный разрешённый QA-кандидат Workflow с этими
исходниками; установленный dev/production ради этого отчёта не менялся.

PR остаётся draft. Установка и merge не выполнялись.
