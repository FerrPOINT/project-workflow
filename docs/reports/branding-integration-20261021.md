# Брендинг и выбор Base: квалификация 21 октября 2026

Base runtime/reference fingerprint: `57eb3995a6c7`; поставочный anchor —
`.base-ui-revision`. SDK/skills pins не изменялись.

- Hosted run `39537456017`, head `a32cb704`: 3008 unit/UI tests PASS,
  60 subtests PASS, 5 skipped, 96 deselected; global coverage 94.20%.
  Job затем упал на отдельной Node-фикстуре, поэтому целый quality job — FAIL.
- Node-фикстура обновлена на реальный backing control `namespaceThemeIcon`.
  9/9 PASS; проверяется и заполнение, и пустой сброс до saved-отметки.
- На своей временной PostgreSQL 17.6 выполнены все 96 integration cases: PASS.
  Установленный runtime и его credentials не использовались, ресурсы удалены.
- Mypy выявил недопустимый для заявленного Python 3.10 `asyncio.timeout`.
  Полный deadline сохранён через `asyncio.wait_for`; size cap 64 KiB,
  no-redirects и фильтрация credentials неизменны. Два теста ограниченного
  Python-3.10 API дали RED до исправления и PASS после него.
- Итоговый bridge: 26 tests PASS, 100% покрытия изменённого модуля (43 statements),
  ruff PASS, mypy PASS для 139 файлов. Новый scoped результат не объявляется
  повторным полным global coverage измерением.
- После PostgreSQL-прогона изменены только формат wiring (normalized AST
  совпадает) и изолированный branding bridge; DB/migration/integration inputs
  сохранены. Доказательства этих стадий разделены.

Source, hosted CI, временный QA и установленная платформа — разные стадии.
Последующий full hosted gate нового head учитывается отдельно; старый job не
объявляется зелёным. Настоящий масштаб текста 200% в IAB остаётся непроверенным.
Merge, production и установка не входят в эту поставку.
