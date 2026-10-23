# Повторное использование подготовленного Docker context

Explicit opt-in API передаёт один approved frozen transport между этапами.
Сначала canonical caller проверяет готовый image. Если Docker build ещё нужен,
prepared context позволяет пропустить повторные Git archive, tar processing,
извлечение исходников, compatibility exporter и gzip.

## Подготовка один раз

Запускать issuer в уже подготовленном frozen producer environment Python3.11.15.
Текущий `locked-core-v1` использует project lock без UI extra и requirements overlay.
Он сам не устанавливает зависимости и не строит
image. Родитель output должен существовать; destination создаётся новым.

```sh
python -B -m scripts.build_runtime_image prepare-context \
  --revision <exact-source-commit> --skills-root <skills-git-root> \
  --output <owned-new-directory> --context-max-bytes <owner-budget-bytes>
```

Для Base catalog добавить `--catalog-variant base`. Issuer сохраняет текущие
archive/exporter semantics и полную проверку Base package, включая physical
role/skill hashes. Output содержит только `context.tar.gz` и `receipt.json`.
Успех возвращает `directory` и `receipt_sha256`; родитель сохраняет этот digest
в своём approved operation record. Checksum, полученная из произвольного
соседнего marker, не является approval.

Budget ограничивает payload и cold uncompressed context по действующей политике
владельца. Это предел размера данных, не измерение или лимит RAM приложения.
Новый cache/index, автоматический поиск, очистка и замена готового output отсутствуют.
Windows publication использует no-replace rename; Linux — `renameat2` с
`RENAME_NOREPLACE`. Не поддерживающий atomic primitive host получает отказ.

## Передача готового transport

Consumer использует стандартную библиотеку; UV/site packages не нужны:

```sh
python -S -B -m scripts.build_runtime_image build \
  --revision <exact-source-commit> --skills-root <skills-git-root> \
  --image project-workflow:<exact-source-commit> \
  --prepared-context <approved-directory> \
  --prepared-context-receipt-sha256 <externally-approved-receipt-sha256> \
  --context-max-bytes <owner-budget-bytes>
```

Три prepared параметра обязательны вместе. Request независимо сверяет immutable
source commit/tree, catalog и skills repository/pin/blob. Dirty working files не
подменяют committed bytes. Проверяются strict receipt, полный gzip digest/size,
состав directory, regular files, links/hardlinks и read/publication bookends.
Docker получает именно проверенные bytes. Runtime bundle digest покрывает
подмножество transport и не заменяет gzip digest.

При ошибке consumer не запускает exporter, UV или legacy producer для ремонта.
Bounded resource flags требуют аттестованный pinned Dockerfile frontend.
Build args, labels и subsequent image/provenance checks сохраняются.
Base `workspace_workflow.build` принимает явно переданный reference и budget
в пределах existing export policy; без reference остаётся прежний UV caller.
Root/candidate CLI adoption не включён автоматически.

Issuer и image build запускаются под существующим parent host admission.
Эти product CLI не приобретают второй slot и не заменяют daemon cleanup owner.

Reader сравнивает общую file identity между path/handle APIs; их `ctime` может
иметь разную точность на Windows. Полные stamps, включая `ctime`, сравниваются
до/после чтения отдельно для открытого handle и пути. Различие API не вызывает
повторную подготовку, а изменение файла во время чтения остаётся ошибкой.

## Подключение к владельцу BuildKit в Base

`inspect-context` принимает те же revision/skills/prepared параметры и возвращает
проверенный receipt. Payload читается потоком, без его сохранения в памяти.
Это проверка transport, а не доказательство собранного image.

`plan-build` дополнительно принимает `--image` и `--build-name sdlc-build-<32hex>`.
Он возвращает `workflow-prepared-build-plan/v1` с точным Docker argv, исходным
receipt и его внешним pin. Archive/exporter/gzip/UV/Docker не запускаются.
Имя допустимо только как [история BuildKit](https://docs.docker.com/reference/dockerfile/#buildkit-built-in-build-args):
объявление `ARG BUILDKIT_BUILD_NAME` в recipe запрещено, чтобы identity операции
не стала compiler input. Build args и provenance labels принадлежат общей функции
с обычным product producer.

Новый Base caller передаёт уже сжатые immutable bytes напрямую в Docker stdin.
Распаковки на Windows нет: Unix executable modes и исходный gzip сохраняются.
Он удерживает общий slot и durable owner до terminal daemon record с тем же
именем и frontend argument. Unknown/ambiguous metadata сохраняет ownership для
read-only recovery; завершение CLI не доказывает завершение daemon.
Последующий ready lookup проверяет original sealed proof без повторного plan,
install/export/compile и без требования хранить disposable payload.

Native qualification и принятие exact quality packet выполняются отдельно.
Добавление API в source не переключает tooling/SDK/UI/skills/operator pins.

## Граница доказательства

Receipt версии `workflow-prepared-context/v1` утверждает конкретные frozen bytes.
Effective producer environment equivalence остаётся `UNQUALIFIED`: Git ambient
policy, refs/export-subst, Python/zlib и dependencies не становятся полным
герметичным input seal. Изменившаяся среда не переписывает approved artifact.
Для automatic lookup по текущим inputs нужен отдельный qualified contract.
Правила archive: [Git documentation](https://git-scm.com/docs/git-archive#_attributes).

Focused source controls: `tests/test_prepared_context.py` в reviewed unit lane.
Они используют tiny Git и настоящий package validator, Docker подменён recorder.
Это не native image/resource qualification и не runtime acceptance.
Политика и остальные lanes: [TESTING](TESTING.md). Принятую версию общего
стандарта Base выбирать по [AGENTS.md](../AGENTS.md) и workspace quality pin.
