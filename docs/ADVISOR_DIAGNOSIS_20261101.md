# Advisor: сквозной диагноз и границы выпуска

Согласование исходников с принятым общим UI, 2026-11-02: обычный merge master.
Целевой PM/configured-cli набор — 115 PASS. Полный unit/coverage запуск дал
3407 PASS, 4 FAIL, 15 штатных skips и покрытие 94,11%. Два отказа вызваны
декодированием UTF-8 subprocess как cp1252 на Windows, один — устаревшим
AST-хешем намеренно расширенного PromptBuilder, один — захваченным при импорте
значением версии prompt в default argument fingerprint. Исправления прошли
все 50 адресных проверок; прежние байтовые регрессии generic prompt и строгие
AST-хеши response parser сохранены. Ruff и mypy 166 файлов PASS.
Полный gate после адресных исправлений заново не заявляется; модельный блокер
ниже остаётся, установка и новые платные вызовы не выполнялись.

## Кандидат PM v1 после диагностики, 2026-11-02

**Модельная приёмка не пройдена; кандидат3d84a60 не устанавливать и не мержить.**
Завершены48/48 заранее заданных клиентских запросов; новая live-приёмка не начата.

Реализовано и проверено отдельно, **не установлено**: короткий judge prompt только
для проверенной configured PM роли; worker procedure не передаётся, шесть полей
ответа сохранены. Фактическая версия `supervisor-evaluator-pm-v1` записывается в
diagnostics/fingerprints; generic v12 и старые frozen receipts сохраняются.
PM-DRAFT-02/03 не наследуют covered, включая повторную проверку после HTTP и
technical-error fallback. Phase01 и общий history reader не менялись.
Итоговый целевой набор на продукте3d84a60:341 PASS; Ruff и mypy166 файлов PASS.
Моки доказывают механику, не качество модели. Runtime93c14f8/PM23/catalog10 прежние.

Перед новыми вызовами независимо зафиксирована разметка следующего сравнения:

| Случай | Checks / evidence | Verdict |
| --- | --- | --- |
| 164 | CC / C | PASS |
| 170,171 | CCCC / CC | PASS |
| 163 | CCCCC / CC | PASS |
| 133 | MMCMC / MM | PARTIAL |
| 153 | MMMC / MM | PARTIAL |
| Нет контекста, производный164 | MM / M | PARTIAL |
| Не совпадает receipt hash, производный163 | CMCMC / CM | PARTIAL |

**Golden revision v2 до вызовов:** C4 случая133 изменён с covered на missing,
поскольку текст заявляет точное согласие при противоречащих hashes. То же правило
применено к синтетическому receipt control. Это исправление согласованности разметки,
не переписывание старого результата или исходного golden. В синтетическом163 меняется
только `content_hash=` внутри уникального блока сохранённого подтверждения; hashes
документа/показа остаются прежними. Модельный control не заменяет серверный тест прав.

Baseline/candidate сравниваются попарно, по три вызова каждого на случай, максимум48.
Захваченные164/170/171 воспроизводятся точно;133/153/163 — явно обозначенная
реконструкция с ordinal IDs и пустой историей, не production replay.
Защищённый runner: `Q/advisor_pm_policy_20261102.py`, выход
`Q/advisor-pm-policy-v1-20261102/`. До первого вызова сохраняются все inputs/goldens;
неизвестный исход не выполняется повторно. Разметка v2 и все inputs зафиксированы
до первого вызова; после просмотра ответов не менялись.

### Результат фиксированного сравнения

| Случай | v12: verdict в трёх вызовах | PM v1: verdict в трёх вызовах | Exact items: v12 / PM |
| --- | --- | --- | --- |
| 164 | PARTIAL ×3 | PASS ×3 | 0/3 / 3/3 |
| 170 | PARTIAL ×3 | PARTIAL ×3 | 0/3 / 0/3 |
| 171 | PASS, PARTIAL, PARTIAL | PARTIAL ×3 | 1/3 / 0/3 |
| 163 | PASS ×3 | PASS ×3 | 3/3 / 3/3 |
| 133 | PARTIAL ×3 | PARTIAL ×3 | 0/3 / 0/3 |
| 153 | PARTIAL ×3 | PARTIAL ×3 | 1/3 / 3/3 |
| Нет контекста (с оговоркой ниже) | PARTIAL ×3 | PARTIAL ×3 | 3/3 / 3/3 |
| Не совпадает receipt hash | PARTIAL ×3 | PARTIAL ×3 | 0/3 / 0/3 |

Суммарно: v12 exact8/24, ложных PARTIAL8/12 положительных,24 расхождения items;
PM v1 exact12/24, ложных PARTIAL6/12 положительных,22 расхождения items (из135).
Оба варианта отвергли12/12 отрицательных отчётов; false PASS и format errors здесь0.
Все48 ответов HTTP200/finish=stop. Это ограниченный combined-policy first-attempt
bench, не production error rate, не проверка upstream retries и не live PM [11].

### Дополнительный анализ после проверки

| Наблюдение | Проверяемое основание | Вывод и граница |
| --- | --- | --- |
| Контекст164 проходит3/3 вместо0/3 | Из judge удалена процедура; полный report1313 символов сохранён | Устранено круговое требование на выбранном случае, не доказана общая надёжность |
| 170 остаётся PARTIAL3/3 | Report5454 символа содержит FULL, source/ответы, ключ публикации, фактическую команду requirements read, revision/hash. Ответы требуют полный raw publication/readback, хотя E179 не требует дубликат CLI output | Семантическая оценка достаточности evidence; не потеря документа сборщиком. Внутренний механизм модели неизвестен |
| 171 остаётся PARTIAL3/3 | Report6394 символа сохранён. Один ответ требует дополнительный brief/answer mapping; два — новое подтверждение FULL/readback. Документ и hashes согласованы | Отказ добавляет условия. Дословной короткой исходной фразы в171 самом нет, но есть подробное изложение решений владельца; нельзя объявлять это потерей в runner или требовать дословную цитату без контракта |
| 133 и receipt control: verdict верный, covered/missing неверны | Модель замечает несовпадающий hash, но часть относящихся к нему критериев помечает covered | Ошибка отдельных критериев не скрывается правильным PARTIAL. Свободное объяснение не доказывает семантическую согласованность |
| Прежний механизм coverage исправлен детерминированно | Настоящие SQLite ledgers в unit-тестах: phase02/03, новый report/revision/hash, semantic/transport/format failure, выбранные prompt/version/fingerprint | Это квалификация механики с synthetic authorities, не самостоятельная модельная приёмка |

Фактический system сокращён **5297 -> 2000** символов; суммарные system+user:
164 **9345 -> 4355**,170 **14409 -> 9044**,171 **15532 -> 9984**.
FULL, существенные ответы и критерии не удалены. Объём уменьшился; на164 круговой
отказ в candidate не воспроизвёлся. Вклад одного только объёма отдельно не измерен,
а ложные отказы170/171 сохранились.

Read-only review runner выявил две оговорки. Синтетический absent-context использует
delegate=None, тогда как исходный captured164 разрешает DELEGATE: это не производный
случай с единственным изменением report. В обоих сравниваемых arms настройка одинакова,
но control нельзя выдавать за exact captured replay. Кроме того, runner проверял
JSON/IDs, но не отдельный запрет DELEGATE для фазы без delegate. Ни один ответ не
содержит DELEGATE, поэтому наблюдаемые170/171 этим не объясняются. Продуктовая проверка
allowlist не изменена. Старые inputs/runner/results не исправляются задним числом.

**Одна следующая гипотеза:** в коротком system заменить глобальное перечисление
`actual commands/readbacks` единым правилом: формат и достаточность доказательств
определяет конкретный checks/evidence. Обязательные FULL, identity/hash, результаты,
receipt и реальные противоречия сохранить. Условие `wherever the stated items require
them` уже ограничивает прежнюю фразу, поэтому её причинное влияние не доказано;
не объявлять такую замену проверенным исправлением и не дописывать исключения под170/171.
В текущем этапе эта гипотеза **не реализована и не испытана**: лимит48 исчерпан.

Решение: сохранить опубликованную реализацию как непринятый Draft, установленный v12
не менять. Полный release gate, образ, установка, два новых чата и browser acceptance
не запускались после отказа обязательного модельного gate. Итоговый выпуск и мерж
остаются незавершёнными, а не заменяются ростом exact score.

## Актуальный результат, 2026-11-02

Read-only диагностика завершена. Три независимых исполнителя проверили архитектуру,
контекст и разметку; интегратор сверил runtime и воспроизвёл сборку запросов без
модели. **Новых inference-вызовов: 0 из разрешённых 48.** Сборок, установок,
публикаций, бизнес-команд и изменений Hermes/PM/credentials не было.
Исправление оценки и новая live-приёмка PM остаются следующим этапом.

### Baseline и маршрут модели

- Установлен продукт `93c14f88a0c38051857c584c3f8bc2281351db54`, evaluator v12,
  image `bdfb02159989`. Read-only наблюдение 2026-11-02 06:25 UTC подтверждает
  прежний healthy-контейнер, catalog10/hash `ae220f915d33987f...`, effective PM23 [8].
- Source baseline `651649d` содержит только документацию поверх продукта93c14f8.
  Настройки внутри контейнера: `app-test`, timeout120s, max_tokens4000,
  reasoning_effort=none; wire temperature=0.1. Это параметры клиента, не доказательство
  того, что upstream применил каждый из них.
- `/v1/models` возвращает лишь alias `app-test`. Read-only
  `/model/info?model=app-test` возвращает **три записи `chatgpt/gpt-6-luna`** [8].
  Это текущие метаданные маршрутизатора, не идентификация backend каждого старого
  запроса и не доказательство причины ошибки модели. Исторический route selection,
  fallback, cache и преобразования upstream-параметров здесь не установлены.
  Назначение endpoint описано в [официальной документации LiteLLM](https://docs.litellm.ai/docs/proxy/model_management).
- Env selector `PROJECT_WORKFLOW_CATALOG_VARIANT=legacy` выбирает seed, а не
  заменяет уже опубликованный catalog10. Фактические три фазы PM взяты из API;
  наличие этого env не означает, что задача получила старый Workflow.

### Фактическая архитектура

```text
PM / оригинальный Hermes
  -> terminal -> project-workflow step (report, key, expected version)
  -> Auth + Tracker assignment / task checks
  -> final phase only: latest revision + saved owner confirmation checks
  -> Workflow: contract + current report + historical covered IDs
  -> advisor HTTP request (system + user, JSON object)
  -> strict parser -> version/contract recheck -> history + phase transition
  -> PM reads result / next step
  -> after complete=true: separate Tracker PM completion -> Backlog / Ready
```

| Сведения / ответственность | Источник и получатель | Граница доверия |
| --- | --- | --- |
| Контекст исполнителя | CLI step: инструкции, история, recent verdicts, шаблон отчёта; Hermes также читает Tracker/обсуждение | Это **не** вход advisor. Полный native prompt Hermes в данной диагностике не захвачен |
| Контракт оценки | PromptBuilder: system v12, task/phase, worker procedure, checks/evidence с IDs, prior covered, текущий report | Внешняя переписка, прежние полные отчёты, SOUL/skills и отдельные Tracker readbacks автоматически не добавляются |
| Идентичность, назначение, версии | Серверные Auth/Tracker проверки; fence и повторная проверка состояния перед commit | Модель не выдаёт права и не заменяет эти проверки |
| Актуальная редакция и owner receipt | Финальный configured CLI проверяет Tracker до модели и перед terminal commit | Проверенные факты не передаются advisor отдельным типизированным блоком; он видит их изложение PM |
| FULL документ, полнота, согласованность с brief | Текущий отчёт PM, checks/evidence; оценивает модель | Ссылки на старый отчёт не восстанавливают его содержимое. Утверждение PM не становится независимым API-подтверждением |
| Формат и сохранение | ResponseParser, state/contract fingerprint, frozen evaluation snapshot | Проверяют структуру/целостность/актуальность, **не истинность семантической оценки** |
| Бизнес-переход | Tracker completion после принятого Workflow | PASS или terminal receipt сами по себе ещё не доказывают Backlog / Ready |

Точки реализации: [PromptBuilder / parser](../project_workflow/infrastructure/llm.py),
[сборка оценки и commit](../project_workflow/supervisor/evaluate.py),
[накопление coverage](../project_workflow/supervisor/core.py),
[проверки Tracker](../project_workflow/infrastructure/configured_cli_tracker.py),
[configured CLI](../project_workflow/application/configured_cli.py),
[контекст PM](../project_workflow/supervisor/context.py),
[завершение PM](../project_workflow/infrastructure/single_task_delivery_instructions.py).

### Что воспроизведено в механике

1. Сборщик v12 побайтово воспроизводит **реально сохранённые user prompts**
   164/167/170/171 из catalog10, report, items, prior IDs и разрешённых verdicts.
   System совпадает. LLM-source frozen1a8a9ee и текущего продукта имеет один Git blob;
   различие LF/CRLF независимых checkout не считается изменением политики [9].
2. Во всех четырёх захваченных вызовах: HTTP200, finish=stop, одна попытка,
   без усечения/маскирования значимых данных и без исчерпания output budget.
   Строгий parser возвращает тот же PARTIAL. **Сервер не заменил PASS на PARTIAL**.
3. До трёх попыток предусмотрено только для невалидного формата ответа;
   исходный запрос дополняется format correction, не прежним ответом модели.
   Валидный PARTIAL семантически не перепроверяется. State/fingerprint сверяются
   после HTTP; изменённые phase/version/contract не принимаются молча.
4. `previously_covered` объединяет исторические covered для task/phase/mode/cycle.
   Нет привязки к revision/hash документа; поздний missing не отменяет старый covered.
   Prompt одновременно требует сохранить его: `keep them in covered`, хотя текущая
   фаза требует полный актуальный пакет. In-memory проверка production history reader
   воспроизводит это без БД [9]. Сервер **не** объединяет covered с валидным ответом
   модели автоматически. Это противоречие входа, не доказанная причина первых отказов:
   у164 и170 предыдущего покрытия нет.
5. Parser отклоняет пересечение/пропуск/чужие IDs и неправильную структуру.
   Синтетический структурно корректный PASS с фразой «полный документ отсутствует»
   принимается [9]: свободное объяснение не проверяется на семантическое противоречие.
   Это граница parser, не предложение добавить regex-исправление verdict.

### Перепроверенная разметка и причины

`C` = covered, `M` = missing; C1.../E1... идут в порядке checks/evidence
**собственного сохранённого контракта случая**, не нового каталога задним числом.

| Случай | Ожидаемые checks / evidence; verdict | Фактическое поведение | Подтверждённый слой / неопределённость |
| --- | --- | --- | --- |
| 164 | CC / C; PASS | missing check289, PARTIAL | Модель требует отправку текущего отчёта и его будущий результат вопреки system rule19. В сохранённых парных сравнениях164/167 (по три на случай, шесть суммарно) удаление worker procedure меняет PARTIAL на PASS; причина framing подтверждена узко, внутренний механизм модели неизвестен |
| 167 | CC / C; PASS | missing check289, PARTIAL | То же круговое требование при наличии assignment/read facts; не потеря текста, не transport/parser |
| 170 | CCCC / CC; PASS | PARTIAL, дополнительное доказательство авторства ответов | Report содержит source, реальные ответы, FULL revision1 и matching publication/readback hash. Все непустые поля сохранённого документа совпадают. Независимой attestation контракт не требует; модель добавляет обязанность, для которой не получила отдельного источника |
| 171 | CCCC / CC; PASS | PARTIAL, заявлено расхождение с решениями владельца | FULL revision2, publication/readback/receipt согласованы; конкретное противоречие не названо. Реальная переписка поддерживает содержание. Отказ не объясняется отсутствием FULL или поздним feedback |
| 133 | MMCCC / MM; PARTIAL | Исторический PARTIAL, но C2/E2 ошибочно covered; в controlled replay встречается false PASS | В текущем отчёте противоречивые hashes (50 и64 символа, не сокращённый prefix) мешают связать документ/показ/receipt. Receipt существует; отсутствие владельца не является причиной. Семантическая ошибка отдельных items остаётся даже при правильном verdict |
| 153 | MMMC / MM; PARTIAL | PARTIAL с таким же missing | Реальный недостаток PM: перечисление разделов и ссылки на прежние отчёты не содержат текущий FULL пакет. Это не ложный отказ |
| 163 | CCCCC / CC; PASS | Исторический PASS | FULL, конкретная хронология представления и matching receipt достаточны. Нельзя задним числом требовать новую publication/readback справку или независимое подтверждение показа |

Для170/171 проверены реальные owner messages и все непустые поля revisions1/2 [10].
Позднее замечание об optional assignee не используется против более раннего отчёта.
Отдельные ошибки PM тоже сохранены: запрос подтверждения до phase2 PASS и изменённый
report/version с прежним operation key. Последний409 возникает **до advisor**;
это корректная защита от конфликтующего payload, а не сетевой повтор оценки.

### Избыточность, сопоставимость и неизвестное

- Worker procedure смешана с критериями результата. Собственную отправку отчёта
  нельзя доказать в этом же отчёте; system содержит исключение, но исходные команды
  остаются рядом. Для164/167 есть контролируемый эффект, для остальных переносить
  этот вывод без проверки нельзя.
- System v12 содержит общие code-regression/orphaned-artifact правила и примеры
  других профессий; их применимость к PM неочевидна. Это лишняя нагрузка контракта,
  **но причинный вклад длины/примеров отдельно не установлен**.
- Advisor повторно рассуждает о правах/receipt по изложению PM, хотя финальный сервер
  уже проверяет их. Независимо удостоверять автора каждого ответа по отсутствующему
  источнику не является оговорённой обязанностью judge. Качество документа и реальное
  согласование противоречий остаются его предметом; убрать их из проверки нельзя.
- Exact captured requests164/167/170/171 и восстановленные original-shape47 не равны:
  у последних нормализованы IDs, prior coverage пуст, delegate отсутствует, по одному
  вызову на слот против production format retries. Исторические133/153/163 не имеют
  такого же полного захвата отправленного prompt; восстановление обозначается явно.
- Masked-hash corpus исключён из оценки качества. В broad47 отдельно учитываются
  false PASS, false PARTIAL, неверные items и format errors; один агрегат exact
  не доказывает безопасность и не является production error rate.
- **Append-only QA correction:** negative B в evidence179-only trial меняет первый
  hash в171 — это receipt, а не publication/readback. Ожидание PARTIAL/check290 missing
  обосновано; ожидание evidence179 missing неоднозначно, вероятнее covered.
  Старые inputs/goldens/results не переписаны. Поэтому прежние **4/12 exact — только
  исторический score старой разметки**; 0/6 positive PASS и6/6 negative PARTIAL остаются
  наблюдениями. Уже отвергнутую дополнительную фразу evidence179 повторять не нужно.
- Полный native prompt PM, исторический backend route и скрытая причина модельной
  ошибки не установлены. Объяснения/confidence модели — её утверждения, не доказательство.
  Для зафиксированных выводов новых вызовов не потребовалось; возможность дальнейших
  различающих экспериментов не исключается.

### Один минимальный следующий пакет: контракт входа configured PM

Это предложение, **не выполненное изменение и не принятая новая политика**.

1. Только configured PM с явными evaluation items: judge получает checks/evidence
   и текущий report без worker procedure. Полные инструкции CLI для PM не менять.
   Явно оставить задачу judge: оценить предоставленный пакет, а не выдать собственную
   аттестацию происхождения недоступной ему переписки.
2. Только PM-DRAFT-02/03: не наследовать covered предыдущего отчёта. Применить это
   одинаково при сборке до модели и при повторной проверке state/fingerprint,
   включая technical-error snapshot. Историю не удалять; reader, остальные роли,
   phase01 coverage и legacy-вызовы сохранить.
3. Выполнить два изменения последовательно с отдельными регрессиями, чтобы не
   смешивать причинные факторы. Версионировать изменённый evaluator contract;
   frozen v12 и старые исполнения продолжать читать/валидировать прежним способом.
4. Регрессии: текущий FULL отсутствует после старого covered; новая revision/hash;
   ложный старый covered позднее опровергнут; корректный полный пакет; controls133/153/163;
   неизменность других ролей/legacy; current owner/revision guards до/после модели.
   Моки доказывают механику, не качество оценки. После них — ограниченная заранее
   размеченная проверка модели, затем два PM-сценария до Backlog / Ready без Analyst.

Пакет устраняет доказанное противоречие входа, **не гарантирует устранения false PASS**.
Не нужны новая модель-проверяющий, resolver, БД/API, обход consent, автоматический
PASS или переписывание valid verdict. Диагноз завершён; исправление и выпуск PM — нет.

## Исторические результаты 2026-11-01

Следующие таблицы сохраняют ход предыдущих экспериментов. Их ограничения и исправление
разметки из актуального раздела имеют приоритет над прежними агрегатами.

## Установлено, наблюдалось, предложено

Установлен Workflow `93c14f88a0c38051857c584c3f8bc2281351db54`: диагностика и
исправление маскирования поверх evaluator v12, без изменения его политики.
Normal Apply `daced4eb`, image `bdfb02159989`. Финальный gate этого SHA:
**3319 passed,73 passing subtests,15 skips; coverage94.0827%; PostgreSQL132 passed** [1].
Это техническая квалификация диагностического выпуска, не приёмка PM.

Сохранённый live baseline: catalog10, effective PM23, модель `app-test`.
PM23, app-test, Hermes и Fleet не менялись в рассматриваемых экспериментах.
Кандидат v17 исключает worker procedure из evaluator-входа при наличии authoritative
evaluation items; критерии, evidence и отчёт сохраняются. v18 дополнительно
переносит verdict в конец JSON-примера. **v17 и v18 НЕ установлены и НЕ приняты**.
Source-кандидат, replay и установленный runtime не взаимозаменяемы.

## Случаи и диагноз

| Случай | Ожидание контракта | Наблюдение | Подтверждённое / неизвестное | Исправление / проверка |
| --- | --- | --- | --- | --- |
| Live SDLC-24, history164–167 | Оценить прочитанный контекст и работу в назначенной задаче; текущий отчёт не содержит своего будущего ACK/verdict. | Четыре круговых PARTIAL. Для 164/167 missing относится к check289: модель требует отправку текущего отчёта и чтение результата. HTTP200, finish=stop, сохранённый вход не усечён [2]. | Подтверждено добавление процедурного/будущего условия к проверке. Это semantic mismatch, не установленный transport/parse/config failure. Внутренняя причина модели неизвестна. | Отделение procedure проверено на exact captured inputs, без изменения live history [3]. |
| Captured164/167, по 3 пары | Сохранить положительные критерии, отчёты, IDs, prior coverage, parser и settings. | Control: **0/6 PASS**; no-procedure: **6/6 PASS**; no-procedure + verdict-last: **6/6 PASS** [3]. | Контролируемое изменение входа устранило наблюдавшийся отказ на этих случаях. Это не доказательство общей надёжности и не отдельный выигрыш verdict-last на них. | Сопоставлять с отрицательными случаями широкого набора; не повторять до PASS. |
| Original-shape 47 случаев × 3 | Exact совпадение verdict, per-item coverage/missing и blockers с разметкой, включая отрицательные случаи. | Control **35/141**, v17 **91/141**, v18 **98/141** exact; ошибки **26 / 4 / 2** [4]. | Все указанные ошибки имеют category=response_contract: технически невалидный ответ отделён от валидного, но неверного semantic verdict. Улучшение агрегата не закрывает остаточные ошибки. | Сохранять строгий parser; не исправлять verdict автоматически и не считать исключённые ошибки успешными ответами. |
| SDLC-22:133, отрицательный original-shape | PARTIAL: разметка требует missing для полного представления документа и matching saved consent. | False PASS: control round3; v17 rounds2/3; v18 round3 [4]. | v18 и control дали по **1/3 false PASS** на этом случае; одинаковая частота на трёх повторах НЕ гарантирует non-regression. Ошибочное покрытие отдельных items встречается и при PARTIAL. | Обязательный отрицательный контроль; нельзя компенсировать false refusals ослаблением FULL/latest/hash/consent guards. |
| Ранний masked corpus | Оригинальные факты и hash-binding должны сохраниться. | Broad counts **INVALID**: маскирование изменило значимые hashes. Результаты сохранены, но исключены из quality gate [5]. | Подтверждён дефект входного представления; эти числа не характеризуют качество evaluator на оригиналах. | Использовать corrected original-shape inputs с проверкой provenance, не смешивать две серии. |
| Live SDLC-25,170/171 | FULL документ, совпадающий readback, описанные ответы владельца достаточны; separate consent не нужен для phase2. | Требования1/2 сохранены, последняя редакция отдельно подтверждена; advisor всё равно требует дополнительную attestation. | Независимый review не находит заявленного расхождения. Установка диагностики историю171 не меняет. | Исправление оценки пока не найдено; задача Draft/InProgress, не Backlog/Ready [6]. |
| SDLC-25, corrected report409 | Неизвестная одинаковая команда сохраняет key/version/report; изменённый отчёт получает новый key. | Один key использован с двумя версиями и разным содержимым;409, acceptance_unknown=false. | Подтверждён правильный payload-conflict отказ, CLI теряет различимую причину. | Draft-инструкция уточняет новый key; серверную защиту не ослаблять [6]. |
| Phase1 instruction5-only | Оба положительных случая PASS, оба отрицательных PARTIAL, по3 вызова. | Positive5/6 PASS, negative6/6 PARTIAL; exact11/12. | Частичное улучшение, не устранение ошибки. Фазы2/3 byte-identical каталогу10. | Не опубликовано; оставшийся отказ сохранён [7]. |
| Phase2 evidence179-only |170/171 PASS; нет документа либо hash противоречив — PARTIAL. | Positive0/6 PASS; negative6/6 PARTIAL; исторический exact4/12 требует QA correction выше. | Добавленная фраза не устраняет ложный отказ; один отрицательный item был неоднозначно размечен. | Вариант отклонён, не опубликован [7]. |

Exact в таблице означает совпадение всей размеченной оценки, а не только PASS.
Пары164/167 являются отдельной когортою и не добавляются к знаменателю141.
V18 broad errors: invalid JSON на SDLC-23:152 round2 и :162 round3 [4].
Сохранённые message/coverage показывают внешнее поведение; они не являются hidden
chain-of-thought. Ни влияние порядка полей, ни «раннее решение модели» не объявляются
доказанным внутренним механизмом. Для provider/config failure нужны свои trace-признаки.

## Граница решения и следующие шаги

- Не объявлять v17/v18 готовыми по росту exact или положительному bench: остаются
  false PASS, semantic mismatches и parse failures; advisor не удалён и verdict не переписывается.
- На зафиксированном кандидате разобрать оставшиеся расхождения по item/rationale/excerpt,
  сохраняя FULL document, latest revision/hash и human-owner consent. Следующий replay
  ограничить заранее заданными изменёнными входами и положительными/отрицательными случаями.
- Полные обязательные gates относить к точному финальному SHA отдельно от replay;
  результаты установленного `1a8a9ee` не переносить на v17/v18 как их квалификацию.
- Live-приёмка требует отдельного решения интегратора и фактического пользовательского пути.
  **Полная PM acceptance не выполнена; SDLC-24 и SDLC-25 не завершены.** PM23 и ранее
  захваченные инструкции остаются прежними; source-правка не активирует конфигурацию.

## Проверяемые источники

`Q` ниже — защищённый operator evidence-каталог `pm-runtime-recovery-20261030`.
В документ перенесены только агрегаты и диагноз; secrets, private IDs и raw reports не включены.

1. `Q/workflow-diagnostics-release-93c14f8-install.json`; `Q/diagnostics-release-v12-93c14f8-20261101/{full.log,full.json,pg.json}`; image smoke `evidence/workflow161-diagnostics-release-v12-1bb0424554/result.json`.
2. `Q/workflow161-diagnostics-only-v12-release-20261101.md`; `Q/diagnostics-only-v12-live-baseline.json`; `Q/diagnostics-only-v12-sdlc24-{initial,latest}-history.json`.
3. `Q/sdlc24_ack_bench_164_167.json`; checkpoints в `Q/sdlc24-captured-ack-comparison-3x-20261101/` и `Q/sdlc24-verdict-last-positive-3x-20261101/`.
4. `checkpoint.json` в `Q/original-shape-{control,variant,verdict-last}-3x-20261101/`; adapters `Q/run_original_shape_47.py`, `Q/run_original_shape_verdict_last.py`.
5. Архивные `Q/saved-truth-{baseline,no-instructions}-3x-20261101/`; corrected adapter `run_original_shape_47.py` проверяет исходные hashes и запрещает redacted acceptance inputs.
6. `Q/diagnostics-only-v12-sdlc25-{latest,final}-history.json`, `Q/diagnostics-release-93c14f8-sdlc25-preserved-history.json`; protected `Q/pm-default-diagnostics-v12-20261101/sparse/` observations/confirmation/replay/terminal readbacks.
7. `Q/sdlc24-context-instruction5-only-3x-20261101/checkpoint.json` и `Q/sdlc25-preparation-evidence-only-3x-20261101/checkpoint.json`; fixed runners `run_context_instruction12.py`, `run_preparation_evidence12.py`.
8. `Q/advisor-chain-diagnosis-20261102/baseline.json`; read-only collector `advisor_chain_baseline_20261102.py`. Route response сохранён только whitelist-полями и SHA256, без credentials. Внутри установленного контейнера дополнительно прочитаны безопасные поля `get_settings()`; private operator transcript не публикуется.
9. `Q/advisor-chain-diagnosis-20261102/offline-checks.json`; `advisor_chain_offline_checks_20261102.py`. Git blob LLM-source `faa0379bae3d002783b128bff9b9d80e05d9e0a9`; db_connections/model_calls/business_commands=0. Это диагностические проверки, не live CLI acceptance.
10. `Q/pm-default-diagnostics-v12-20261101/sparse/summary-readback.json`: source `/messages/0`, ответы `/messages/30` и `/messages/40`, позднее замечание `/messages/54`, confirmation notice `/messages/62`, документы `/requirements/revisions/0` и `/requirements/revisions/1`. Исторические133/153/163: `Q/pm-default-simple-20261031/{full,sparse}/workflow-history.json`, соответственно `/records/2`, `/records/10`, `/records/0`; сравнивались оригинальные `worker_report` и `result.required_checks/required_evidence`, не только объяснение модели.
11. `Q/advisor-pm-policy-v1-20261102/prepared-inputs.json`, SHA256 `39d422dc37780a489cdefce7d539dbe057d339405fba384f66d3c6dd20dd1ec2`; `checkpoint.json`, SHA256 `4780d70985d020f2e39a6267debe422c3edbd7a969f8b094454ecfdbc530fac6`. Source `3d84a60` и runner hash зафиксированы в manifest. Candidate170: slots3/19/35;171: slots5/21/37. Все48 slots complete, неизвестных повторных вызовов нет. `targeted-junit.xml`:341 PASS на том же продукте; полный gate не запускался. Полные inputs и sanitizer outputs остаются в защищённом evidence, без публикации credentials.
