# Workflow на едином origin PDLC

Gateway публикует `/workflow/`, снимая prefix перед передачей приложению.
`UI_BASE_PATH=/workflow` задаёт ссылки, API, namespace navigation, redirects
и cookie paths. Default пустой и сохраняет standalone поведение. Значение
валидируется: один локальный сегмент, без внешнего адреса, query и traversal.

`AUTH_PUBLIC_ORIGIN` остаётся bare origin для CSRF Origin comparison;
prefix нельзя встраивать в него. Callback строится из origin + UI_BASE_PATH
+ `/sso/callback`. Transaction cookie имеет exact callback path, session
cookie — path раздела. Issuer — общий Central Auth того же внешнего origin.

Маршруты и internal/runtime endpoints не переименовываются. Catalog, namespace,
workflow identifiers, modes, БД и CLI `step/history` не меняются. Публичный
prefix не даёт новых прав и не снимает SSO проверки.

Проверки: SSO negative cases, prefixed rendered navigation/API/error links,
compile/lint, затем coordinated image/ingress gate и live вход через Central
Auth. Runtime PASS фиксируется отдельно от source/HTTP unit tests.
