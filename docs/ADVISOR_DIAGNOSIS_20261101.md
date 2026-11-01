# Advisor: диагноз и границы выпуска, 2026-11-01

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
| Phase2 evidence179-only |170/171 PASS; нет документа либо hash противоречив — PARTIAL. | Positive0/6 PASS; negative6/6 PARTIAL, exact4/12. | Добавленная фраза не устраняет ложный отказ. | Вариант отклонён, не опубликован [7]. |

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
