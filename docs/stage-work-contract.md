# Работа профессии: задача, обсуждение, результат и передача

Текущий single-task профиль строит один порядок для всех семи профессий:
прочитать задачу и участников → выполнить работу → сохранить комментарий →
передать результат через разрешённый переход. Developer имеет initial/rework,
поэтому проверяются восемь режимов и 24 внутренние фазы.

## Начало и результат работы

Первой операцией остаётся настоящий fenced Workflow step без report.
После admission читать `sdlc context`, требования и `sdlc discussion read` Tracker.
Discussion возвращает настоящее название/описание и комментарии всех авторов.
Читать каждую страницу до `next_after=null`, сохраняя исходный snapshot.
Результаты предшественников дополнительно читать по принятым immutable refs;
обычное обсуждение не заменяет sealed role artifacts или требования.

Профессия выполняет собственную работу на этой же task=root. Архитектура —
план/дизайн, без создания children. Developer сохраняет exact candidate/checks;
Reviewer/Tester дают независимый вердикт с actionable findings; DevOps проверяет
фактически установленный результат и его происхождение.

После принятия финального Workflow report обновить полное обсуждение. Сохранить настоящий комментарий
через `task-tracker sdlc discussion publish --task UUID --from-file FILE` с
`body`, текущим typed `fence` и выданным `FLEET_STAGE_COMMENT_KEY`.
Комментарий содержит работу, revision/candidate, проверки/evidence, замечания,
ограничения и запрошенный следующий stage/status. Он не сообщает о переходе
как о свершившемся факте.

После неопределённого ответа — `discussion operation` с тем же ключом и тем же
исходным телом. Проверить comment ID, автора, task/assignment/execution/revision,
hash UTF-8 тела и сам комментарий в обсуждении. Нет readback, запись изменилась
или удалена — успешная передача запрещена. Заимствование credentials и generic
issue/comment mutation не являются обходным путём.

## Оценка и фактический переход

Для финального Workflow report подготовлено резюме фактической работы. Сам
комментарий публикуется после принятия отчёта и до business handoff в Tracker.
Собственный будущий `complete=true` receipt и будущий Tracker transition не
являются входом этой же оценки: они появляются после неё. Будущий комментарий
также не является её входом: PARTIAL/BLOCKED допускают дальнейшую работу до
замораживания итогового текста. PM сначала получает настоящее согласие владельца
на exact revision/hash, завершает Workflow и сохраняет комментарий перед концом
run; прежние human-only и typed resume guards сохраняются.

Supervisor оценивает выполнение текущей фазы. Полноценные Review/Testing могут
завершиться с бизнес-результатом `rework`. Это не принятие candidate и не основание
придумывать rollback target внутри Workflow. Missing phase obligations и
противоречивые утверждения не становятся PASS из-за слова `rework`.
Prompt перечисляет только настроенные routing verdicts; parser продолжает
отклонять ненастроенные rollback/delegate вместо преобразования в PASS.

Technical role получает принятый Workflow receipt, сохраняет и проверяет
итоговый комментарий, публикует typed proposal
при живом run и заканчивает run. Fleet после настоящего native terminal
вызывает guarded Complete; Tracker проверяет сохранность комментария повторно.
Затем проверяется фактический lifecycle stage/status и identity принятого
результата. Комментарий, proposal, текст агента и exit code не заменяют переход.

## Совместимость и проверка

Требуется согласованный Tracker API/CLI, Fleet с run-bound comment key и новый
Workflow manifest/catalog hash. Старый установленный manifest — drift;
observation/init не исправляют его молча и не переписывают историю назначений.
Изменение инструкций не предоставляет отсутствующие tools, API или grants.
SDK/UI/operator и Hermes pins независимо сохраняются.

`test_stage_discussion_instructions.py` проверяет порядок во всех восьми режимах;
`test_evaluator_stage_outcomes.py` — связь business rework и phase completion,
allowed verdicts и сохранённый fail-closed parser. Управляемые ответы LLM в unit
не доказывают качество настоящей модели или живого результата.

Отдельный ручной протокол Base `docs/acceptance/SDLC_PROOF.md` содержит 17 случаев:
семь профессий, несколько авторов и страниц, неопределённый ACK, повторы, отказы,
lease/ACL/isolation, rework и независимый бизнес-оракул. Он не входит в обычные
тесты; helper проверяет файлы evidence и не сертифицирует runtime PASS.

Исторические Base configured-tools каталоги и старые qualification receipts
не переписываются этим пакетом. Их прежние результаты не подтверждают новые
инструкции. В частности, ранее найденные self-referential completion checks
такого каталога нельзя принимать за валидную приёмку single-task профиля.
