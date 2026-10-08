# Изолированная установка PDLC control plane

Для первой установки PDLC builder принимает explicit `--catalog-variant base`.
Он читает Base candidate из exact Workflow commit и manifest из закреплённого
Git commit приватного Base. Default `legacy` прежних installations не изменён.
Dockerfile закрепляет выбор в image; runtime использует тот же каталог.

```powershell
python -B -m scripts.build_runtime_image build --revision <exact-workflow-sha> `
  --image pdlc1-project-workflow-runtime --skills-root ../services-base `
  --catalog-variant base
```

В новой БД штатная миграция устанавливает семь workflow, 11 режимов и 33 фазы.
Developer имеет только initial/rework. Skills, HOME и agent processes этот шаг
не устанавливает. История и данные существующего SDLC не переносятся.

Descriptor `base-workflow-controlplane/v1` подтверждает каталог и package pins,
но **не автономное исполнение**. Legacy assignment/runtime credentials в Base
variant отклоняются fail-closed; допускается только read-only catalog token.
Новый assignment/receipt adapter и полноценная автономная приёмка B-SDLC-03
остаются отдельной работой. Это не включение старого Business bridge в Base.

Проверки: provenance tests, Base installation tests, managed catalog/runtime
API tests; затем actual immutable image build, native migration и `/health`.
Существующие installations не переключаются изменением глобального default.
