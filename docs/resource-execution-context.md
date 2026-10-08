# Версионированный контекст ресурсов

Бизнес-Namespace принадлежит Admin. Legacy Workflow namespaces, Projects,
CLI IDs, общие profiles и active catalog version сохраняются. Отдельный v2
контекст ссылается на NamespaceRef, TaskRef и RepositoryRefs и выбирает
конкретную версию Workflow profile/mode. Два Namespace используют один profile.

`GET/PUT /api/v2/execution-contexts/{identity}` требует verified human identity.
Owner readers проверяют Tracker/Forge refs до transaction; сама transaction
фиксирует current profile/version. UUID и operation ID immutable; original
actor/payload replay читается до HTTP. Повреждённая saved projection даёт 503.

Alembic `0007_resource_execution_contexts` следует 0006 в существующей schema
`project_workflow`. Аддитивная таблица `resource_execution_contexts` содержит
request, verified projection, profile/mode и creator subject. Down migration
отказывает в потере совместимого cohort. Runtime gates остаются false,
adapter — `namespace-context-v2/foundation-v1-disabled`.

Readers задаются `PROJECT_WORKFLOW_NAMESPACE__TRACKER_URL/TRACKER_TOKEN_FILE`
и `FORGE_URL/FORGE_TOKEN_FILE`. Они не пересылают human PAT, не принимают origin
из запроса, отключают redirects, ограничены 10 s и 64 KiB.
`PROJECT_WORKFLOW_NAMESPACE__MACHINE_SUBJECTS` классифицируется до human routes.

Этот API не активирует installer/PM foundation и не меняет Base-v3 catalog,
skills pin или принятые runtime settings. Совместимость и runtime rollout
проверяются отдельными gates; прежний Workflow #97 остаётся baseline до них.
