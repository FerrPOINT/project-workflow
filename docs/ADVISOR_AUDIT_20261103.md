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
Credentials исполнителем source-аудита не читались. Полный suite не повторялся.
Продуктовые исходники и установленная конфигурация не изменены. Последующая живая
проверка интегратора учитывается отдельно ниже, а не приписывается source-аудиту.

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

## Живая Проверка Интегратора

После source-аудита выполнены три новые вымышленные задачи через настоящий Fleet
API, без подмены Auth, Tracker, модели или ответов CLI. Оператор принимал решения
QA-владельца; требования, отчёты фаз и обе команды завершения выполнял только PM.
Генераторы не изменяли конфигурацию вокруг сообщений. Workflow/Fleet/Auth/Hermes
не пересобирались, не перезапускались и не обновлялись в этой проверке.
Readiness до старта: PM revision25, catalog12, blockers=[], app-test/high.
После завершения IDs и images четырёх контейнеров совпали с исходными.

| Задача Tracker / Workflow | Сценарий | Результат |
| --- | --- | --- |
| FLEETQA-30 / SDLC-30 | Полный запрос: список покупок с границами количества | Документ1 без вопросов, отдельное подтверждение, Backlog/Ready; истории182/183/184 PASS |
| FLEETQA-31 / SDLC-31 | Полный запрос: расходы, точные денежные суммы, дата и валидация | Документ1 без вопросов, отдельное подтверждение, Backlog/Ready;185/186/188 PASS |
| FLEETQA-32 / SDLC-32 | Скудная идея, уточнения, замечание, новая редакция | Документы1/2, отдельное подтверждение2, Backlog/Ready;187 PASS,189/190 PARTIAL,191/192 PASS |

Одиннадцать оценок: **9 PASS,2 PARTIAL**, каждая с одной попыткой, HTTP200,
finish_reason=stop, без format repair. Все model user objects содержат ровно
phase/allowed_verdicts/criteria/previously_covered/report; report вложен объектом,
равным разобранному входу CLI. Нет усечения, UUID и 64-символьных значений hashes
в model user. Служебный snapshot вне model messages закономерно хранит версии/ID.
Однако «никакого лишнего» ещё не достигнуто: source188/192 содержит слова о hash,
receipt и authorized owner, которые PM добавил сам. Значений квитанции/хэша нет,
но эти технические пояснения не нужны смысловой проверке. Они остаются дефектом
подготовки report, как и показ checksum владельцу. Builder не очищает документы
слепыми заменами. Сохранены логические system/user, не raw HTTP bytes/headers.

### Причина Отказа И Продолжение

- **189:** источник задавал два допустимых статуса, но не начальный. PM сам
  назначил «Нужно ответить» и заявил, что вопросов нет. PARTIAL по C3 обоснован.
  PM передал конкретный вопрос владельцу; оператор ответил обычным языком и добавил
  третий статус с требованием сохранности. Технических подсказок не было.
- **190:** PM передал новые решения, но упустил из source прежнее решение владельца
  о статусе «Закрыта». В переписке оно было, в запросе Advisor — нет. Отказ относится
  к недостатку входного отчёта, не к потере builder или parser. Одни prior marks
  не восстанавливают отсутствующий исходный факт. Advisor также отозвал прежний E2.
- **191:** PM самостоятельно восстановил пропущенное решение в source и получил
  PASS. Сохранённая редакция2 не публиковалась повторно. Это исправление изменённого
  отчёта с новым ключом, а не скрытый повтор неизменённого PARTIAL до PASS.
- **Остаточная ошибка 189:** E2 засчитан за утверждение «вопросов нет», хотя C3
  выявил неотвеченный вопрос. Независимый разбор считает E2 missing. Это одна
  подтверждённая ошибочная положительная item-отметка, не ложный PASS всей фазы.
  Исторический ответ не изменён; контр-разметка выполнена после наблюдения и не
  выдаётся за заранее заданную qualification. Автоматическое исправление verdict
  или поиск ключевых слов для этого не добавлялись.

Полезные документы не потеряны при передаче JSON. Однако буквальное совпадение
отчёта с readback не универсально:186/188 заменяют в одном сценарии «данных» на
«значений»;191 добавляет пояснение об источнике решения внутрь scope. Остальные
поля этих документов совпадают. Это не скрытое усечение builder и не выявленное
изменение бизнес-правила, но утверждать byte-exact копию нельзя. Финальный192
передаёт все десять полей сохранённой редакции2 без таких изменений.

### Независимые Readbacks И Интерфейс

- Прямой установленный Tracker CLI и Fleet подтвердили Backlog/Ready для всех
  трёх задач. Назначен тот же PM, assignment_version=1; все2/2/4 runs completed,
  других агентов в их runs нет. Analyst не назначен. Это не live-приёмка других ролей.
- Повторы исходных операций сохраняют task/chat/operation IDs и число сообщений
  и запусков:66/2,64/2,56/4. Устаревшее подтверждение редакции1 SDLC-32 отклонено409;
  принято именно2 в Draft. Новую live-инъекцию lost ACK или повтор completion
  в этой когорте не выполняли; прежние тесты не выдаются за новую проверку.
- Chromium149,Firefox151,WebKit26.5: открыты dialogue/requirements трёх задач,
  видны Backlog/Ready и все десять полей сохранённых документов. После штатной
  загрузки предыдущих сообщений все16 user/assistant сообщений присутствуют в
  правильном порядке в каждом движке. Два ранних expenses-снимка сделаны до
  завершения GET; сохранены. Адресная проверка с ожиданием текста первого сообщения
  подтвердила отсутствие потери истории; это исправление ожидания QA, не приложения.
- Screenshots сняты на375x812,1920x1080,2560x1440. Открыты и просмотрены mobile
  shopping requirements, desktop expenses dialogue и wide sparse requirements.
  Проверка не объявляется полной accessibility/theme/zoom acceptance.
- Во всех трёх движках сохраняются **P2**: Auth login `normalizeBranding` падает
  с hex ReferenceError; после reload UI показывает недоступное подтверждение вместо
  сохранённого. **P3**: null waiting_reason отображается как «Недоступно»;
  неприменимый checkpoint — как отсутствие данных. HTTP-ошибок на исследованных
  Fleet страницах и заблокированных бизнес-запросов нет; clean browser gate не принят.
- Hex вызван потерянным alias импортированной функции в classic SSR export.
  Base `e4f73d8` уже содержит исправление; проверенный exporter:96 и Auth bootstrap:22
  сохраняют `const hex = isHex`. Локальный VM smoke работает; удаление alias в памяти
  воспроизводит отказ. Новая реализация или правка Hermes не нужны; установленному
  Auth нужна отдельная квалифицированная доставка имеющегося исправления.
- В Fleet source verified=false живёт только в mutation-state; reload его теряет.
  На проверенном main7fd6ff2 GET confirmation ещё отсутствует. Уже открытый
  [Fleet#162](https://github.com/FerrPOINT/fleet-control/pull/162), HEAD600d816,
  добавляет нужный receipt readback; новый endpoint повторно не реализовывался.
  PR mergeable/open, но checks пусты — это не доказательство квалификации.
  Source-only неизвестный исход confirmation после reload также не восстанавливается
  самим RevisionConfirmation. Live lost ACK не провоцировался.

Фактические входы/ответы и документы: [live JSON](evidence/workflow-advisor-audit-live-20261103.json).
DOM-сверки без credentials: [browser summary](evidence/workflow-advisor-audit-browser-20261103.json).
Исходные screenshots/stack traces: `.local/pm-browser-sidecar-20261103/audit-*`.

## Минимальный Следующий Пакет

1. Добавить189 как отрицательную item-регрессию E2 и190/191 как пару потери и
   восстановления source. Сначала проверить общую согласованность объяснений на
   фиксированных входах; не добавлять status-specific prompt или semantic эвристику.
2. Уточнить существующую инструкцию подготовки report: сохранить действующие
   исходные решения, нужные для проверки документа, при дополнении/исправлении;
   использовать сохранённый документ вместо перепечатывания. Не подгружать весь чат
   и не создавать resolver. Оставить в report бизнес-факт согласования; убрать
   пояснения о hash/receipt/authority из source и ответа владельцу. Серверные
   проверки при этом сохраняются вне model messages.
3. Механические края закрывать узкими воспроизводимыми тестами: одинаковая политика
   делегирования в builder/parser/formatter; согласованный допуск пустой рубрики и
   terminal proof; штатная обработка RecursionError ответа провайдера. Для текущего
   PM sync-каталога не нужны новые фазы или переписывание runtime.
4. Независимо квалифицировать уже готовые Auth fix и Fleet#162, не реализовывать
   повторно и не объявлять установленными по одному наличию кода в Git.

**Итог:** обычный PM-путь работает на трёх новых задачах. Лишний цикл локализован
в неполном source PM; одна item-ошибка Advisor и механические края остаются открыты.
Аудит не равен утверждению об идеальной модели или полной готовности семи профессий.

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
- Auth login hex ReferenceError локализован интегратором отдельно. Чистая трёхдвижковая
  browser acceptance и DOM proof persisted confirmation после reload здесь не
  подтверждены. API booleans не выдаются за DOM proof. Kubernetes/новая установка,
  полный 3779-test gate и повторная модельная квалификация не выполнялись.

`Q` обозначает существующий локальный operator evidence-каталог
`pm-runtime-recovery-20261030`; сырые отчёты, документы, токены и credentials
в этот аудит не копировались. Исправление находок и дальнейшая live QA являются
отдельной работой, не результатом этого read-only исследования.
