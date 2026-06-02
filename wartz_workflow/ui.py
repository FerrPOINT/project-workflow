"""Minimal Web UI for wartz-workflow — FastAPI + Jinja2.

Сервер на уникальном порту (default 7788):
    python -m wartz_workflow.ui
    python -m wartz_workflow.ui --port 9000

Точки входа CLI:
    hrflow ui          # запустить в foreground
    hrflow ui --daemon # запустить в background
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from . import conversation, schema, state, config

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = 7788
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
DB_PATH = Path(config.WARTZ_DIR) / "conversation.db"

# ── FastAPI App ─────────────────────────────────────────────────────────
app = FastAPI(title="wartz-workflow UI", version="1.0.0")

# Templates (inline if dir missing, else filesystem)
if TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
else:
    templates = Jinja2Templates(directory=str(BASE_DIR))


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def load_phases() -> list[dict]:
    """Загрузить фазы из YAML."""
    try:
        phases = schema.load_phases()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "checks": [c.__dict__ for c in p.checks],
                "evidence": [e.__dict__ for e in p.evidence],
                "instructions": [i.__dict__ for i in p.instructions],
                "gate_type": p.gate_type or "pass",
                "rollback_target": p.rollback_target,
                "max_cycles": p.max_cycles,
            }
            for p in phases
        ]
    except Exception:
        return []


def load_tasks() -> list[dict]:
    """Список задач из conversation.db."""
    if not DB_PATH.exists():
        return []
    rows = conversation.get_messages(None, limit=1000)
    # Group by task_id
    tasks = {}
    for row in rows:
        tid = row.get("task_id", "unknown")
        if tid not in tasks:
            tasks[tid] = {
                "task_id": tid,
                "jira_key": row.get("jira_key", tid),
                "message_count": 0,
                "last_message": None,
                "phases": set(),
            }
        tasks[tid]["message_count"] += 1
        tasks[tid]["last_message"] = row.get("created_at")
        if row.get("phase_id"):
            tasks[tid]["phases"].add(row["phase_id"])

    return [
        {
            **t,
            "phases": list(t["phases"]),
        }
        for t in tasks.values()
    ]


# ═══════════════════════════════════════════════════════════════════════
#  PAGES
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Dashboard / overview."""
    phases = load_phases()
    tasks = load_tasks()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "phase_count": len(phases),
            "task_count": len(tasks),
            "blocker_count": len(config.BLOCKER_PHASES),
            "phases_preview": phases[:5],
            "tasks_preview": tasks[:5],
        },
    )


@app.get("/phases", response_class=HTMLResponse)
def phases_page(request: Request):
    """Все фазы workflow."""
    phases = load_phases()
    return templates.TemplateResponse(
        "phases.html",
        {"request": request, "phases": phases, "phase_order": config.PHASE_ORDER},
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    """Список задач."""
    tasks = load_tasks()
    return templates.TemplateResponse(
        "tasks.html",
        {"request": request, "tasks": tasks},
    )


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: str):
    """История сообщений по task_id."""
    messages = conversation.get_messages(task_id, limit=500) if DB_PATH.exists() else []
    return templates.TemplateResponse(
        "task.html",
        {"request": request, "task_id": task_id, "messages": messages},
    )


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
    """Конфигурация приложения."""
    phases = load_phases()
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "wartz_dir": config.WARTZ_DIR,
            "db_path": str(DB_PATH),
            "blockers": config.BLOCKER_PHASES,
            "delegated": config.DELEGATED_PHASES,
            "phase_order": config.PHASE_ORDER,
            "key_patterns": [
                {"name": "jira_standard", "example": "AAT-123"},
                {"name": "internal_neiro", "example": "TASKNEIROKLYUCH-42"},
                {"name": "legacy_hr", "example": "HRRECRUITER-7"},
                {"name": "simple_dev", "example": "DEV-1"},
            ],
            "total_phases": len(phases),
        },
    )


# ═══════════════════════════════════════════════════════════════════════
#  API (JSON)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/phases")
def api_phases():
    return {"ok": True, "phases": load_phases()}


@app.get("/api/tasks")
def api_tasks():
    return {"ok": True, "tasks": load_tasks()}


@app.get("/api/task/{task_id}/messages")
def api_task_messages(task_id: str):
    messages = conversation.get_messages(task_id, limit=500) if DB_PATH.exists() else []
    return {"ok": True, "task_id": task_id, "messages": messages}


@app.get("/api/config")
def api_config():
    return {
        "ok": True,
        "wartz_dir": config.WARTZ_DIR,
        "blockers": config.BLOCKER_PHASES,
        "delegated": config.DELEGATED_PHASES,
        "phase_order": config.PHASE_ORDER,
    }


# ═══════════════════════════════════════════════════════════════════════
#  CLI ENTRY
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(prog="hrflow ui", description="Запустить веб-UI")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help=f"Порт (default {DEFAULT_UI_PORT})")
    parser.add_argument("--host", default="0.0.0.0", help="Хост (default 0.0.0.0)")
    parser.add_argument("--daemon", action="store_true", help="Запустить в background")
    args = parser.parse_args()

    # Ensure templates dir
    ensure_templates()

    if args.daemon:
        print(f"Starting wartz-workflow UI on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0

    print(f"Starting wartz-workflow UI on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


# ═══════════════════════════════════════════════════════════════════════
#  INLINE TEMPLATES
# ═══════════════════════════════════════════════════════════════════════

PAGE_STYLE = """
<style>
:root{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--accent:#38bdf8;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;}
*{box-sizing:border-box;font-family:system-ui,-apple-system,sans-serif}
body{background:var(--bg);color:var(--text);margin:0;padding:0;line-height:1.6}
.container{max-width:1200px;margin:0 auto;padding:20px}
header{background:var(--card);padding:16px 20px;border-bottom:1px solid #334155;display:flex;justify-content:space-between;align-items:center}
header h1{margin:0;font-size:1.3rem;color:var(--accent)}
nav a{color:var(--text);text-decoration:none;margin-left:20px;opacity:.8}
nav a:hover{opacity:1;color:var(--accent)}
.card{background:var(--card);border-radius:8px;padding:20px;margin-bottom:16px;border:1px solid #334155}
.card h2{margin-top:0;color:var(--accent);font-size:1.1rem}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #334155}
th{color:#94a3b8;font-size:.85rem;text-transform:uppercase}
tr:hover{background:rgba(56,189,248,.05)}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600;background:#334155}
.badge-ok{background:rgba(34,197,94,.2);color:var(--ok)}
.badge-warn{background:rgba(245,158,11,.2);color:var(--warn)}
.badge-block{background:rgba(239,68,68,.2);color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.msg-row{padding:10px 0;border-bottom:1px solid #334155}
.msg-meta{font-size:.8rem;color:#94a3b8;margin-bottom:4px}
.msg-content{color:var(--text)}
.msg-user{color:var(--accent)}
.msg-system{color:var(--ok)}
.msg-wizard{color:var(--warn)}
.phase-id{font-family:monospace;color:var(--accent);font-weight:600}
.phase-name{font-weight:500}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
pre{background:#0b1220;padding:12px;border-radius:6px;overflow:auto;font-size:.85rem}
</style>
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>wartz-workflow UI</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <div class="grid">
    <div class="card">
      <h2>Dashboard</h2>
      <p><b>Фаз workflow:</b> {{ phase_count }}</p>
      <p><b>Задач в истории:</b> {{ task_count }}</p>
      <p><b>Blocker фаз:</b> {{ blocker_count }}</p>
      <p><a href="/phases">Все фазы &rarr;</a></p>
    </div>
    <div class="card">
      <h2>Последние задачи</h2>
      {% for t in tasks_preview %}
        <div class="msg-row">
          <div><a href="/task/{{ t.task_id }}">{{ t.jira_key }}</a>
            <span class="badge badge-warn">{{ t.message_count }} msgs</span></div>
          <div class="msg-meta">Последнее: {{ t.last_message or '—' }}</div>
        </div>
      {% else %}
        <p style="opacity:.6">История пуста. Используй <code>hrflow note TASK-123 ...</code></p>
      {% endfor %}
      <p><a href="/tasks">Все задачи &rarr;</a></p>
    </div>
    <div class="card">
      <h2>Фазы workflow</h2>
      <p><a href="/phases">Просмотр всех фаз</a></p>
    </div>
  </div>
</div>
</body></html>"""

PHASES_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Phases — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Все фазы workflow ({{ phases|length }})</h2>
  <table>
    <tr><th>#</th><th>ID</th><th>Name</th><th>Gate</th><th>Checks</th><th>Evidence</th></tr>
    {% for p in phases %}
    <tr>
      <td>{{ loop.index }}</td>
      <td class="phase-id">{{ p.id }}</td>
      <td class="phase-name">{{ p.name }}</td>
      <td><span class="badge {% if p.gate_type == 'blocker' %}badge-block{% endif %}">{{ p.gate_type }}</span></td>
      <td>{{ p.checks|length }}</td>
      <td>{{ p.evidence|length }}</td>
    </tr>
    {% endfor %}
  </table>
</div>
</body></html>"""

TASKS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tasks — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Задачи ({{ tasks|length }})</h2>
  <table>
    <tr><th>Jira Key</th><th>Task ID</th><th>Сообщений</th><th>Фаз</th><th></th></tr>
    {% for t in tasks %}
    <tr>
      <td><b>{{ t.jira_key }}</b></td>
      <td class="phase-id">{{ t.task_id }}</td>
      <td>{{ t.message_count }}</td>
      <td>{{ t.phases|length }}</td>
      <td><a href="/task/{{ t.task_id }}">История &rarr;</a></td>
    </tr>
    {% endfor %}
  </table>
</div>
</body></html>"""

TASK_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ task_id }} — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">История: {{ task_id }}</h2>
  {% for m in messages %}
  <div class="msg-row">
    <div class="msg-meta">{{ m.created_at }} · <span class="badge">{{ m.role }}</span> · Phase {{ m.phase_id or '-' }}</div>
    <div class="msg-content {% if m.role == 'user' %}msg-user{% elif m.role == 'system' %}msg-system{% else %}msg-wizard{% endif %}">{{ m.content }}</div>
  </div>
  {% else %}
  <p style="opacity:.6">Нет сообщений.</p>
  {% endfor %}
  <p><br><a href="/tasks">&larr; Все задачи</a></p>
</div>
</body></html>"""

CONFIG_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Config — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Конфигурация</h2>
  <div class="grid">
    <div class="card"><h2>Пути</h2>
      <p><b>WARTZ_DIR:</b> {{ wartz_dir }}</p>
      <p><b>DB:</b> {{ db_path }}</p>
    </div>
    <div class="card"><h2>Валидация ключей</h2>
      {% for kp in key_patterns %}
        <p><span class="phase-id">{{ kp.name }}</span> — {{ kp.example }}</p>
      {% endfor %}
    </div>
    <div class="card"><h2>Фазы</h2>
      <p><b>Всего фаз:</b> {{ total_phases }}</p>
      <p><b>Blockers:</b> {{ blockers|join(', ') }}</p>
      <p><b>Delegated:</b> {{ delegated|join(', ') }}</p>
    </div>
  </div>
  <div class="card" style="margin-top:16px">
    <h2>Порядок фаз</h2>
    <pre>{{ phase_order|join('\n') }}</pre>
  </div>
</div>
</body></html>"""

HEADER_HTML = """
<header>
  <h1>wartz-workflow UI</h1>
  <nav>
    <a href="/">Dashboard</a>
    <a href="/phases">Фазы</a>
    <a href="/tasks">Задачи</a>
    <a href="/config">Конфиг</a>
  </nav>
</header>
"""


class InlineTemplates:
    """Fallback когда templates/ не существует — inline HTML."""

    def __init__(self):
        self.cache = {}

    def TemplateResponse(self, name: str, context: dict):
        from starlette.responses import HTMLResponse
        html_map = {
            "index.html": INDEX_HTML,
            "phases.html": PHASES_HTML,
            "tasks.html": TASKS_HTML,
            "task.html": TASK_HTML,
            "config.html": CONFIG_HTML,
        }
        tmpl = html_map.get(name, f"<!-- Template {name} not found -->")
        # Simple variable substitution
        rendered = tmpl.replace("{{ style | safe }}", PAGE_STYLE)
        rendered = rendered.replace("{{ header | safe }}", HEADER_HTML)

        # Jinja-like loops
        if "{% for" in rendered:
            return HTMLResponse(self._render_jinja_like(rendered, context))

        # Simple {{ var }} substitution
        for key, val in context.items():
            if isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False, indent=2)
            rendered = rendered.replace(f"{{{{ {key} }}}}", str(val))
        return HTMLResponse(rendered)

    def _render_jinja_like(self, template: str, context: dict) -> str:
        """Минимальный Jinja-like рендер для inline шаблонов."""
        result = template
        # Simple variable substitution
        for key, val in context.items():
            if isinstance(val, str):
                result = result.replace(f"{{{{ {key} }}}}", val)

        # For loops with list-of-dicts
        import re
        for match in re.finditer(r"\{% for (\w+) in (\w+) %\}(.*?)\{% endfor %\}", result, re.S):
            var_name, list_name, body = match.groups()
            items = context.get(list_name, [])
            rendered_items = []
            for idx, item in enumerate(items):
                item_html = body
                # Replace loop variables
                if isinstance(item, dict):
                    for k, v in item.items():
                        item_html = item_html.replace(f"{{{{ {k} }}}}", str(v))
                        item_html = item_html.replace(f"{{{{ t.{k} }}}}", str(v))
                    item_html = item_html.replace("{{ loop.index }}", str(idx + 1))
                rendered_items.append(item_html)

            # Handle else
            parts = match.group(0).split("{% endfor %}")
            full_match = match.group(0)
            result = result.replace(full_match, "".join(rendered_items))

        # strip remaining Jinja tags for else blocks
        result = re.sub(r"\{% else %\}.*?\{% endfor %\}", "", result, flags=re.S)
        result = re.sub(r"\{% (if|for)[^%]*%\}", "", result)
        result = re.sub(r"\{% (endfor|endif) %\}", "", result)

        return result


# ── Ensure templates ──────────────────────────────────────────────────

def ensure_templates():
    """Создать templates/ с inline шаблонами."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "index.html": INDEX_HTML,
        "phases.html": PHASES_HTML,
        "tasks.html": TASKS_HTML,
        "task.html": TASK_HTML,
        "config.html": CONFIG_HTML,
    }
    for name, content in files.items():
        path = TEMPLATES_DIR / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


# Override templates if inline mode
if not TEMPLATES_DIR.exists():
    templates = InlineTemplates()
else:
    # Re-wrap filesystem templates with header/style injection
    _fs = Jinja2Templates(directory=str(TEMPLATES_DIR))

    class WrappedTemplates:
        def TemplateResponse(self, name: str, context: dict):
            # Inject global context
            context["style"] = PAGE_STYLE
            context["header"] = HEADER_HTML
            return _fs.TemplateResponse(request=context["request"], name=name, context=context)

    templates = WrappedTemplates()


if __name__ == "__main__":
    sys.exit(main())
