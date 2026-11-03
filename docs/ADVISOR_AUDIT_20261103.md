# Workflow / Advisor: аудит после #161

## Область И Метод

Проверен master `c715a03265858a027125df43bbb6bcec8334e702`. Checkout
`f0a0c0a2715bed1ea9d0371f54fd8823551cc4ed` имеет то же содержимое
(Git tree `3340858bad52890d156850546af73c777b5baaed`). От установленного
`b33a813926fd7fa1152fb50d341452f6e844064c` отличаются только CHANGELOG,
диагностический документ и новое live evidence; product/test bytes совпадают.

Аудит: чтение исходников, тестов и сохранённого evidence; локальные проверки чистых
функций и извлечённых неизменённых AST-блоков в памяти через Python `-B`.
Реальные сеть, модель, Auth, БД, Docker и бизнес-команды не вызывались.
Credentials не читались. Полный suite не повторялся. Только этот документ добавлен
после отдельного поручения сохранить результат; production не изменён.

**Подтверждённых P0/P1 или обходов security/owner-consent не найдено.**
Это не гарантия отсутствия всех дефектов. Ниже четыре P2: факт механики отделён
от ещё не наблюдавшегося live последствия. Исправления не применялись.

## Подтверждённые Находки

### P2: DELEGATE предлагает действие без исполнения в configured PM

- Источник разрешения: [schema.py:114](../project_workflow/infrastructure/db/schema.py#L114)
  назначает `PhaseDelegate(agent=profession_code, hermes_profile=launch_profile)`
  каждой фазе при сохранённом профиле профессии. [llm.py:326](../project_workflow/infrastructure/llm.py#L326)
  трактует само наличие этого маркера как разрешение DELEGATE.
- Actual SDLC-30: локальные `Q/pm-default-audit-v15-shopping-20261103/full/`
  `sdlc-30-before-183-context-api-readback.json`,
  `sdlc-30-before-184-preparation-valid-api-readback.json`,
  `sdlc-30-latest-final-api-readback.json` содержат DELEGATE во всех трёх prompts.
  Histories 182/183/184 фактически имеют PASS и по одной попытке. Отказ с `n=20`
  не дефект: diagnostics требует `n=1`.
- [core.py:467](../project_workflow/supervisor/core.py#L467) возвращает для DELEGATE
  `(None, None, None)`. [transitions.py:130](../project_workflow/supervisor/transitions.py#L130)
  оставляет текущую фазу и `active`. [formatting.py:63](../project_workflow/supervisor/formatting.py#L63)
  при этом выдаёт команду «Передай выполнение настроенному агенту».
- Локальный repro реальных функций с памятью вместо БД: DELEGATE принят parser;
  phase_id остаётся 10, status=active, phase events отсутствуют, команда делегирования
  присутствует. Этот путь не создаёт назначение и не исполняет передачу.
- Это риск неясного продолжения/ожидания несуществующей передачи, не автоматический
  переход к Analyst и не необратимый deadend. Новый отчёт в текущей фазе возможен.
  Auth/assignment/version и финальное confirmation не обходятся. Ошибочный выбор
  DELEGATE моделью в SDLC-30 не наблюдался; его вероятность не измерялась.

### P2: parallel prompt теряет разрешённое делегирование

- [evaluate.py:324](../project_workflow/supervisor/evaluate.py#L324) создаёт объединённый
  `evaluation_phase` без `delegate`; то же повторяется при перечитывании состояния
  на строке 444. Builder поэтому исключает DELEGATE.
- Одновременно [evaluate.py:271](../project_workflow/supervisor/evaluate.py#L271)
  проверяет допустимость ответа по исходной `phase`, где delegate может быть задан.
- Repro выполняет фактический AST-блок сборки группы: исходный delegate=researcher,
  merged delegate=None, allowed_verdicts=[PASS, PARTIAL, BLOCKED], тогда как исходная
  фаза допускает DELEGATE. Contract и validator расходятся по одной возможности.
- В текущих PM-DRAFT-01/02/03 execution_type=sync; эта parallel-ветка их не затрагивает.
  Live parallel/delegation не выполнялись.

### P2: пустая финальная рубрика совместима с PASS, но не с terminal proof

- [llm.py:395](../project_workflow/infrastructure/llm.py#L395) допускает PASS с
  `evaluation_items=[]`, `assessments={}`, пустыми blockers. Пустые checks/evidence
  разрешены [schemas.py:426](../project_workflow/interfaces/ui/schemas.py#L426).
- [evidence.py:34](../project_workflow/supervisor/evidence.py#L34) запрещает пустой
  `evaluation_items`. Initial [finish_history:443](../project_workflow/application/configured_cli.py#L443)
  такой proof не проверяет; subsequent replay/readback его проверяет.
- Локальный repro: parser возвращает PASS; frozen validator того же пустого
  контракта возвращает `ConflictError: Terminal evaluator contract items are invalid`.
  По коду финальный custom workflow может зафиксировать done, а затем не пройти
  terminal readback. Полный DB/E2E repro не запускался, противоречие валидаторов
  воспроизведено непосредственно.
- У текущих PM-фаз 3/6/7 evaluation items, поэтому этот край не относится к catalog12 PM.

### P2: глубокий JSON ответа провайдера не становится штатной технической ошибкой

- [llm.py:209](../project_workflow/infrastructure/llm.py#L209) вызывает `json.loads`.
  `RecursionError` не входит в обработчики [evaluate.py:274](../project_workflow/supervisor/evaluate.py#L274)
  и [evaluate.py:412](../project_workflow/supervisor/evaluate.py#L412).
- Repro: локальный fake client подаёт в настоящий `_extract_json` строку
  `' {"nested":' + '[' * 3000 + '0' + ']' * 3000 + '}'`. Фактическая функция
  `_evaluate_strict_response` выходит с RecursionError после первой попытки,
  а не с обработанной ошибкой response contract. Реальных model calls=0.
- Следствие по коду: нет штатного retryable BLOCKED и записи evaluation ledger;
  исключение уходит наружу. Это отказ обработки/диагностики, не ложный PASS.
  На 28 сохранённых квалификационных и рассмотренных live ответах такой ошибки нет.

## Проверенная Цепочка

- **Вход:** `PhaseReport.parse` требует ровно source:string, result:object,
  unresolved:list[str]; сохраняет документы, запрещает duplicate keys, non-finite
  числа, invalid Unicode и превышение 32000 символов. Ошибки не раскрывают report.
  Новый malformed report не имеет plaintext fallback; исторический readback не
  является новой отправкой и не переписывает старые отчёты.
- **Builder:** один JSON data object; report вложен объектом один раз. Только
  phase name, allowed verdicts, локальные labels критериев и prior marks текущей
  фазы. Worker instructions/технические IDs автоматически не добавляются. Report
  явно обозначен untrusted evidence, не инструкцией judge.
- **Модель/parser:** фиксируется выбранный json_object/json_schema; неподдерживаемый
  формат не переключается молча. Полный набор labels, строгие bool/reason,
  verdict/coverage/blocker consistency, запрет extra fields/дубликатов. Только
  malformed response получает максимум две попытки с correction в system и тем же
  user. Валидный PARTIAL не повторяется ради PASS; keywords не определяют verdict.
- **Coverage:** только тот же task/phase/mode/cycle; последняя substantive оценка
  неизменённого текста критерия определяет prior mark. Missing отзывает старый
  covered; technical failure не отзывает оценку. Наследование не объединяется с
  новым model verdict вопреки актуальным assessments. Legacy exact-text lookup
  и historical normalization не являются semantic fallback новых отчётов.
- **Server:** routing принадлежит текущему catalog, не модели. После provider call
  перечитываются contract/cursor/fence; CAS, reauthorization и atomic history +
  transition защищают commit. Operation replay привязан к assignment/key и exact
  request digest; изменённый payload не становится прежним успехом.
- **Consent:** финальный PM отдельно сверяет реальный latest revision/hash/owner
  и Draft confirmation до оценки и повторно перед terminal commit. Advisor не
  аттестует истинность API. Сервер не заменяет смысловую оценку документа своей
  эвристикой и не считает inline утверждение подтверждением владельца.
- **Причины/readback:** canonical message собирается из false item reasons и
  blockers; source CLI выводит его без Rich markup, JSON сохраняет ответ.
  History/diagnostics читают сохранённое, не вызывают модель; защищены обычной
  machine/assignment authority и bounds. Terminal proof связан с frozen contract,
  report/request, coverage и receipt tuple/hash. Capture/redaction/budget failures
  не дают автоматический PASS или fallback к незахваченному private тексту.
- **Технический отказ:** обычные timeout/HTTP/refusal/filter/length/schema failures
  блокируют переход с retryable=true и без придуманных semantic reasons. Configured
  операция сохраняет receipt даже технической попытки: тот же key читает её
  результат; новая оценка требует отдельного key и актуальной версии после сверки
  известного исхода. Это не прозрачный повтор модели по старому ключу.

## Повторно Проверенное Evidence

- [Frozen inputs](evidence/advisor-v15-structured-inputs-20261103.json): 14 source
  digests совпали; 14 span roundtrips точно восстановили исходный текст без новых фактов.
- [Qualification](evidence/advisor-v15-structured-qualification-20261103.json): все
  28 сохранённых HTTP bodies побайтно по строкам system/user и структурно целиком
  совпадают с текущим builder; 28 сохранённых ответов прошли текущий parser и frozen
  expected. 14 случаев x 2, app-test/high/4000, json_object, одна попытка каждый,
  новых/reused model calls в этом аудите нет. Это replay проверки данных, не новая
  модельная квалификация или оценка production error rate.
- [Прежнее live evidence](evidence/advisor-v15-live-pm-20261103.json): full/sparse
  SDLC-28/29, шесть phase PASS, rev2 после замечания, отдельный owner confirmation,
  stale revision 409 и initial-request replay. Это существующее evidence, а не
  заново выполненные мной бизнес-действия или новая аттестация API.
- SDLC-30 рассмотрен только по указанным локальным diagnostics 182/183/184.
  Итоги дальнейших новых QA не присваиваются этому аудиту автоматически.

## Точные Непроверенные Границы

- Полный live cross-role/Rework/parallel/delegation отсутствует. Developer/Reviewer
  в 14-case corpus представлены context, а Tester использует приватно уточнённый
  критерий, не доказанную установленную конфигурацию. Это не all-role acceptance.
- Реальный provider json_schema не квалифицирован этим evidence: сохранённые 28
  вызовов используют json_object. Нет новой live adversarial prompt-injection,
  произвольных документов, provider outage/revocation или конкурентных SQL-прогонов.
  Source/tests review таких guards не выдается за их новое исполнение на стенде.
- Два крайних repro (empty rubric и deep JSON) не выполнялись HTTP/DB end to end.
  Не заявляется наблюдённый production инцидент или измеренная частота этих ошибок.
- Установленный старый CLI передаёт report и canonical message через --json;
  доставка нового локального validator/human formatter остаётся отдельным gap.
  Source CLI fixes не считаются уже установленными в agent image.
- Fleet UI hex ReferenceError разбирается владельцем отдельно. Чистая трёхдвижковая
  browser acceptance и DOM proof persisted confirmation после reload здесь не
  подтверждены. API booleans не выдаются за DOM proof. Kubernetes/новая установка,
  полный 3779-test gate и повторная модельная квалификация не выполнялись.

`Q` обозначает существующий локальный operator evidence-каталог
`pm-runtime-recovery-20261030`; сырые отчёты, документы, токены и credentials
в этот аудит не копировались. Исправление находок и дальнейшая live QA являются
отдельной работой, не результатом этого read-only исследования.
