# Quality Gate

Р­С‚РѕС‚ С„Р°Р№Р» С„РёРєСЃРёСЂСѓРµС‚ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Р№ Р»РѕРєР°Р»СЊРЅС‹Р№ quality gate РґР»СЏ `project-workflow`.
GitHub Actions РІ `.github/workflows/ci.yml` СЃРѕС…СЂР°РЅС‘РЅ РєР°Рє РѕРїС†РёРѕРЅР°Р»СЊРЅРѕРµ Р·РµСЂРєР°Р»Рѕ:
job `quality` Р·Р°РїСѓСЃРєР°РµС‚ С‚РµСЃС‚С‹ Рё СЃС‚Р°С‚РёС‡РµСЃРєРёР№ Р°РЅР°Р»РёР· СЃ PostgreSQL 16, Р°
`compose-smoke` СЃРѕР±РёСЂР°РµС‚ СЃС‚РµРє Рё РїСЂРѕРІРµСЂСЏРµС‚ `/health`. Р”Р»СЏ Р»РѕРєР°Р»СЊРЅРѕРіРѕ РІС‹РїСѓСЃРєР°
СЂРµР·СѓР»СЊС‚Р°С‚С‹ РѕРїР»Р°С‡РёРІР°РµРјС‹С… hosted jobs РЅРµ С‚СЂРµР±СѓСЋС‚СЃСЏ; `[skip ci]` РїСЂРµРґРѕС‚РІСЂР°С‰Р°РµС‚
РёС… Р·Р°РїСѓСЃРє РЅР° push/PR. РќР° РёРЅС‚РµРіСЂРёСЂРѕРІР°РЅРЅРѕР№ РІРµС…Рµ РїСЂРѕРІРµСЂРєРё РЅРёР¶Рµ РІС‹РїРѕР»РЅСЏСЋС‚СЃСЏ Р»РѕРєР°Р»СЊРЅРѕ; РґРѕ РЅРµС‘ scoped checks.

РљР°РЅРѕРЅРёС‡РµСЃРєРёРµ argv РЅР°С…РѕРґСЏС‚СЃСЏ РІ `scripts/quality.py`; Make, PowerShell Рё CI
РґРµР»РµРіРёСЂСѓСЋС‚ РµРјСѓ. Coverage РІС‹РїРѕР»РЅСЏРµС‚ РїРѕР»РЅС‹Р№ unit/UI РЅР°Р±РѕСЂ РѕРґРёРЅ СЂР°Р·.

## Р‘Р°Р·РѕРІС‹Р№ gate

```bash
uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras pytest -q -m integration tests/test_postgres_integration.py --timeout=120
uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras pytest -q --cov=project_workflow --cov-report=term --cov-report=xml --timeout=60 --durations=25
uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras ruff check .
uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras mypy project_workflow scripts
git diff --check
```

РћР¶РёРґР°РµРјС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚:

- РѕР±С‹С‡РЅС‹Р№ pytest РїСЂРѕС…РѕРґРёС‚ Р±РµР· РїР°РґРµРЅРёР№; PostgreSQL integration tests РІ РЅС‘Рј
  РїРѕРєР°Р·С‹РІР°СЋС‚СЃСЏ РєР°Рє deselected;
- РѕС‚РґРµР»СЊРЅС‹Р№ PostgreSQL integration gate РїСЂРѕС…РѕРґРёС‚ РЅР° СЂРµР°Р»СЊРЅРѕРј PostgreSQL;
- coverage РѕСЃС‚Р°С‘С‚СЃСЏ РЅРµ РЅРёР¶Рµ С‚РµРєСѓС‰РµРіРѕ Р»РѕРєР°Р»СЊРЅРѕРіРѕ baseline `94%`;
- `ruff`, `mypy` Рё `git diff --check` РЅРµ РЅР°С…РѕРґСЏС‚ РѕС€РёР±РѕРє.

РќР° Unix-like РѕРєСЂСѓР¶РµРЅРёРё С‚РѕС‚ Р¶Рµ РЅР°Р±РѕСЂ РґРѕСЃС‚СѓРїРµРЅ С‡РµСЂРµР· `make quality`; РЅР° Windows
Р±РµР· `make` РёСЃРїРѕР»СЊР·СѓР№С‚Рµ `pwsh -File scripts/quality.ps1 quality`. Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ
С†РµР»Рё `warnings` Рё `compose-ready` РµСЃС‚СЊ Рё РІ `Makefile`, Рё РІ PowerShell helper.

## ResourceWarning Gate

РџРѕСЃР»Рµ РёР·РјРµРЅРµРЅРёР№ РІ С‚РµСЃС‚РѕРІРѕР№ РёРЅС„СЂР°СЃС‚СЂСѓРєС‚СѓСЂРµ, SQLAlchemy layer, UI request
lifecycle РёР»Рё CLI session lifecycle РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕ Р·Р°РїСѓСЃРєР°С‚СЊ:

```bash
uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras pytest -q --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning
```

Р­С‚РѕС‚ РїСЂРѕРіРѕРЅ РґРѕР»Р¶РµРЅ РїСЂРѕС…РѕРґРёС‚СЊ Р±РµР· SQLite connection warnings, РІРєР»СЋС‡Р°СЏ
`PytestUnraisableExceptionWarning`, Рё Р±РµР· Р·Р°РІРёСЃР°РЅРёР№ РЅР° РїРѕРІС‚РѕСЂРЅС‹С… РјРёРіСЂР°С†РёРѕРЅРЅС‹С…
РєРµР№СЃР°С…. Р•СЃР»Рё С‚РµСЃС‚ СЃРѕР·РґР°С‘С‚ `SAUnitOfWork` РІСЂСѓС‡РЅСѓСЋ, РѕРЅ РґРѕР»Р¶РµРЅ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ context
manager РёР»Рё Р·Р°РєСЂС‹РІР°С‚СЊСЃСЏ С‡РµСЂРµР· РѕР±С‰РёР№ pytest lifecycle РІ `tests/conftest.py`. Р•СЃР»Рё
С‚РµСЃС‚ СЃРѕР·РґР°С‘С‚ SQLite engine РЅР°РїСЂСЏРјСѓСЋ, engine РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ disposed РІ teardown.

## PostgreSQL Integration

Integration tests С‚СЂРµР±СѓСЋС‚ Р»РѕРєР°Р»СЊРЅС‹Р№ PostgreSQL СЃ РїСЂР°РІРѕРј СЃРѕР·РґР°РІР°С‚СЊ Рё СѓРґР°Р»СЏС‚СЊ
РІСЂРµРјРµРЅРЅС‹Рµ Р±Р°Р·С‹:

```bash
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=project_workflow
PGPASSWORD=project_workflow
PGDATABASE=project_workflow
```

РќР°Р±РѕСЂ `tests/test_postgres_integration.py` РїСЂРѕРІРµСЂСЏРµС‚ СЂРµР°Р»СЊРЅС‹Р№ РїСѓС‚СЊ CLI
subprocess -> PostgreSQL -> С‚РµСЃС‚РѕРІС‹Р№ OpenAI-compatible HTTP endpoint ->
Supervisor -> PostgreSQL. Р­С‚Рѕ deterministic runtime integration, Р° РЅРµ РїРѕР»РЅС‹Р№
business E2E СЃ РЅР°СЃС‚РѕСЏС‰РёРј РёСЃРїРѕР»РЅРёС‚РµР»РµРј.

РџРѕР»РЅС‹Р№ executor-driven acceptance РѕРїРёСЃР°РЅ РѕС‚РґРµР»СЊРЅРѕ РІ
[`LIVE_TEST_PLAN.md`](../LIVE_TEST_PLAN.md).

## Compose Readiness

Р”Р»СЏ РїСЂРѕРІРµСЂРєРё Р»РѕРєР°Р»СЊРЅРѕРіРѕ runtime:

```bash
docker compose up --build -d --wait
curl --fail http://127.0.0.1:8812/health
```

РћР¶РёРґР°РµС‚СЃСЏ HTTP `200`, `database=ok`, `schema=ok`. РЎС‚Р°РЅРґР°СЂС‚РЅС‹Р№ Compose РїСѓР±Р»РёРєСѓРµС‚
PostgreSQL Рё API С‚РѕР»СЊРєРѕ РЅР° loopback. Р”Р»СЏ СЃС‚Р°РЅРґР°СЂС‚РЅРѕРіРѕ compose-ready РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ
СЃРІРѕР±РѕРґРЅС‹ `127.0.0.1:5432` Рё `127.0.0.1:8812`; РµСЃР»Рё РїРѕСЂС‚ 5432 Р·Р°РЅСЏС‚ РґСЂСѓРіРёРј
PostgreSQL, integration gate РјРѕР¶РЅРѕ Р·Р°РїСѓСЃРєР°С‚СЊ СЃ `PGPORT`, СѓРєР°Р·С‹РІР°СЋС‰РёРј РЅР°
РѕС‚РґРµР»СЊРЅС‹Р№ С‚РµСЃС‚РѕРІС‹Р№ PostgreSQL.

## UI Smoke

Р РµРіСЂРµСЃСЃРёРё РѕР±С‰РµР№ С€Р°РїРєРё РЅР° РѕС‚РґРµР»СЊРЅРѕР№ smoke-Р±Р°Р·Рµ РїСЂРѕРІРµСЂСЏСЋС‚СЃСЏ РєРѕРјР°РЅРґРѕР№
`SMOKE_BASE_URL=http://127.0.0.1:8812 node scripts/check_ui_shell.mjs`.
Р­С‚Рѕ project-owned automated Playwright runner: РґРІР° namespace selectors,
history/reload, service popover РЅР° 320/375/767/768/1920/2560 Рё mobile drawer.
Р СѓС‡РЅР°СЏ РІРёР·СѓР°Р»СЊРЅР°СЏ РїСЂРёС‘РјРєР° РёСЃРїРѕР»СЊР·СѓРµС‚ Codex in-app Browser.
РќР° РЅРµР№С‚СЂР°Р»СЊРЅРѕРј smoke-РєР°С‚Р°Р»РѕРіРµ `workflow-dev` / `workflow-qa` С„Р»Р°Рі
`--owned-fixture` РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕ СЃРѕР·РґР°С‘С‚ Рё СѓРґР°Р»СЏРµС‚ С‚РѕР»СЊРєРѕ СЃРѕР±СЃС‚РІРµРЅРЅРѕРµ РїСѓСЃС‚РѕРµ
РїСЂРѕСЃС‚СЂР°РЅСЃС‚РІРѕ Рё РїСЂРѕРІРµСЂСЏРµС‚ РѕР±Р° selector РїРѕСЃР»Рµ СѓРґР°Р»РµРЅРёСЏ; РёСЃС…РѕРґРЅС‹Рµ Р·Р°РїРёСЃРё СЃРѕС…СЂР°РЅСЏСЋС‚СЃСЏ.

РџРѕСЃР»Рµ Р»СЋР±С‹С… РёР·РјРµРЅРµРЅРёР№ UI/templates/static JS:

РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РѕС‚РґРµР»СЊРЅСѓСЋ РЅРµР№С‚СЂР°Р»СЊРЅСѓСЋ smoke-Р±Р°Р·Сѓ, С‡С‚РѕР±С‹ СЃРєСЂРёРЅС€РѕС‚С‹ РЅРµ Р·Р°РІРёСЃРµР»Рё РѕС‚
РґРµС„РѕР»С‚РЅРѕРіРѕ runtime-РєР°С‚Р°Р»РѕРіР° Рё РїРѕРєР°Р·С‹РІР°Р»Рё РґРІРµ РЅРµР·Р°РІРёСЃРёРјС‹Рµ Р·Р°РїРёСЃРё РґР»СЏ РѕРґРЅРѕР№
РІРЅРµС€РЅРµР№ Р·Р°РґР°С‡Рё:

`prepare_ui_smoke_data.py` РЅР°РјРµСЂРµРЅРЅРѕ РїСЂРёРЅРёРјР°РµС‚ С‚РѕР»СЊРєРѕ РѕС‚РґРµР»СЊРЅСѓСЋ SQLite smoke-Р±Р°Р·Сѓ
РІ `.smoke/ui-smoke.db` РёР»Рё С„Р°Р№Р» `ui-smoke.db`; РѕР±С‹С‡РЅСѓСЋ runtime-Р‘Р” РѕРЅ РѕС‚РєР»РѕРЅСЏРµС‚.

```bash
export DATABASE_URL=sqlite:///$PWD/.smoke/ui-smoke.db
rm -f .smoke/ui-smoke.db
python scripts/prepare_ui_smoke_data.py
python -m project_workflow.interfaces.ui --host 127.0.0.1 --port 8812
```

Р’ РґСЂСѓРіРѕРј С‚РµСЂРјРёРЅР°Р»Рµ:

```bash
npm --prefix .smoke install playwright
SMOKE_BASE_URL=http://127.0.0.1:8812 node scripts/capture_ui_screenshots.mjs
```

PowerShell:

```powershell
$env:DATABASE_URL = "sqlite:///$PWD/.smoke/ui-smoke.db"
Remove-Item -LiteralPath .smoke/ui-smoke.db -ErrorAction SilentlyContinue
python scripts/prepare_ui_smoke_data.py
python -m project_workflow.interfaces.ui --host 127.0.0.1 --port 8812
```

Р’ РґСЂСѓРіРѕРј PowerShell:

```powershell
npm --prefix .smoke install playwright
$env:SMOKE_BASE_URL = "http://127.0.0.1:8812"
node scripts/capture_ui_screenshots.mjs
```

- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/`;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/namespaces`;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/namespaces/new`;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/tasks`;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/tasks?namespace_id=<qa-id>`;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/phases`;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/settings`;
- РѕС‚РєСЂС‹С‚СЊ detail РѕРґРЅРѕР№ Р·Р°РґР°С‡Рё РІ РґРІСѓС… РІС‹Р±СЂР°РЅРЅС‹С… РЅРµР№РјСЃРїРµР№СЃР°С…, РµСЃР»Рё РјРµРЅСЏР»РёСЃСЊ selector,
  task links, theme РёР»Рё РґР°РЅРЅС‹Рµ РІС‹Р±СЂР°РЅРЅРѕРіРѕ РЅРµР№РјСЃРїРµР№СЃР°;
- РѕС‚РєСЂС‹С‚СЊ `http://127.0.0.1:8812/workflows`, РµСЃР»Рё РјРµРЅСЏР»РёСЃСЊ workflow controls,
  С„Р°Р·С‹ РёР»Рё CRUD workflow;
- РїСЂРѕРІРµСЂРёС‚СЊ, С‡С‚Рѕ РІРµСЂС…РЅРёР№ selector РїРµСЂРµРєР»СЋС‡Р°РµС‚ РІС‹Р±СЂР°РЅРЅСѓСЋ РїСЂРѕС„РµСЃСЃРёСЋ, РµС‘ РёРєРѕРЅРєСѓ Рё С†РІРµС‚
  РІ СЃР°РјРѕРј selector, СЃРїРёСЃРѕРє Р·Р°РґР°С‡, dashboard stats Рё `/phases`; Р»РѕРіРѕС‚РёРї РїСЂРёР»РѕР¶РµРЅРёСЏ
  Рё РѕР±С‰РёРµ СЃС‚РёР»Рё РєРЅРѕРїРѕРє СЃРѕС…СЂР°РЅСЏСЋС‚СЃСЏ;
- РїСЂРѕРІРµСЂРёС‚СЊ, С‡С‚Рѕ СЃС‚СЂР°РЅРёС†С‹ Р·Р°РіСЂСѓР·РёР»РёСЃСЊ Р±РµР· console/network РѕС€РёР±РѕРє;
- СЃРѕС…СЂР°РЅРёС‚СЊ full-page screenshot evidence С‡РµСЂРµР· `scripts/capture_ui_screenshots.mjs`;
- СѓР±РµРґРёС‚СЊСЃСЏ, С‡С‚Рѕ screenshot evidence СЃРґРµР»Р°РЅ РЅР° РїРѕР»РЅРѕР№ РЅРµР№С‚СЂР°Р»СЊРЅРѕР№ smoke-fixture
  СЃ Р·Р°РґР°С‡Р°РјРё, С„Р°Р·Р°РјРё Рё РґРІСѓРјСЏ РїСЂРѕС„РµСЃСЃРёСЏРјРё, Р° РЅРµ РЅР° РїСѓСЃС‚РѕР№ РґРµС„РѕР»С‚РЅРѕР№
  Р±Р°Р·Рµ;
- РїСЂРѕРІРµСЂРёС‚СЊ, С‡С‚Рѕ screenshot evidence РЅРµ СЃРѕРґРµСЂР¶РёС‚ СЃС‚Р°СЂРѕРµ РґРµС„РѕР»С‚РЅРѕРµ РёРјСЏ РёР»Рё
  runtime-specific СѓРїРѕРјРёРЅР°РЅРёСЏ РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ РІРЅРµС€РЅРµРіРѕ РёСЃРїРѕР»РЅРёС‚РµР»СЏ, РІРєР»СЋС‡Р°СЏ
  СЃС‚Р°СЂС‹Рµ `flow-*` РєР»СЋС‡Рё Рё РїСЂРѕС‡РёРµ РІРЅСѓС‚СЂРµРЅРЅРёРµ labels; CLI settings РґРѕР»Р¶РµРЅ
  РїРѕРєР°Р·С‹РІР°С‚СЊ РІС‹Р±СЂР°РЅРЅСѓСЋ wrapper-РєРѕРјР°РЅРґСѓ.

Р”Р»СЏ backend-only С‚РµСЃС‚РѕРІС‹С… РёР»Рё РґРѕРєСѓРјРµРЅС‚Р°С†РёРѕРЅРЅС‹С… РёР·РјРµРЅРµРЅРёР№ browser smoke РЅРµ
РѕР±СЏР·Р°С‚РµР»РµРЅ.

## CLI Wrappers

РџРѕСЃР»Рµ РёР·РјРµРЅРµРЅРёР№ РІ CRUD РЅРµР№РјСЃРїРµР№СЃРѕРІ, bootstrap РёР»Рё CLI selector path РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕ
РїСЂРѕРІРµСЂСЏС‚СЊ РіРµРЅРµСЂР°С†РёСЋ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёС… РєРѕРјР°РЅРґ:

```bash
python scripts/install_namespace_clis.py --bin-dir <dir>
```

РЎРєСЂРёРїС‚ С‡РёС‚Р°РµС‚ РЅРµР№РјСЃРїРµР№СЃС‹ РёР· PostgreSQL, СЃРѕР·РґР°С‘С‚ wrapper-РєРѕРјР°РЅРґС‹ РёР·
`cli_command`, РІС‹СЃС‚Р°РІР»СЏРµС‚ `PROJECT_WORKFLOW_NAMESPACE_ID=<id>` Рё РІС‹Р·С‹РІР°РµС‚
С‚РѕР»СЊРєРѕ `project-workflow step/history`. `project-workflow` РЅРµ РїРѕР»СѓС‡Р°РµС‚ РЅРѕРІС‹С…
РїСѓР±Р»РёС‡РЅС‹С… РєРѕРјР°РЅРґ: wrapper names СЏРІР»СЏСЋС‚СЃСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕР№ CLI-РєРѕРјР°РЅРґРѕР№ РЅСѓР¶РЅРѕРіРѕ РЅРµР№РјСЃРїРµР№СЃР°.

## References

- [README](../README.md) вЂ” launch modes and command overview.
- [Architecture](architecture.md) вЂ” runtime and auth boundaries.
- [Live Acceptance](../LIVE_TEST_PLAN.md) вЂ” executor-driven E2E evidence.
- [Database Reset](database-reset.md) вЂ” clean local Compose baseline.
