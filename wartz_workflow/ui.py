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
import datetime
import json
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from . import conversation, schema, config, state, phases

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
#  WIZARD
# ═══════════════════════════════════════════════════════════════════════

def get_task_current_phase(jira_key: str) -> str:
    """Определить текущую фазу задачи из state или conversation."""
    ts = state.load_state(None, jira_key)
    if ts:
        return ts.get("current_phase", "-1")
    return conversation.get_last_phase(jira_key) or "-1"

def build_ui_checklist(phase: schema.Phase) -> list[dict]:
    """Собрать чеклист для фазы в формате для UI."""
    items: list[dict] = []
    seen: set[str] = set()

    for check in phase.checks:
        k = check.description.strip().lower()
        if k and k not in seen:
            seen.add(k)
            items.append({"id": f"c{len(items)}", "text": check.description, "type": "check", "command": check.command or ""})

    for inst in phase.instructions[:5]:
        k = inst.step.strip().lower()
        if k and k not in seen:
            seen.add(k)
            items.append({"id": f"i{len(items)}", "text": inst.step, "type": "instruction", "example": inst.example or "", "command": ""})

    for ev in phase.evidence:
        k = ev.item.strip().lower()
        if k and k not in seen:
            seen.add(k)
            items.append({"id": f"e{len(items)}", "text": ev.item, "type": "evidence", "command": ""})

    return items


@app.get("/wizard/{jira_key}", response_class=HTMLResponse)
def wizard_page(request: Request, jira_key: str):
    """Интерактивный wizard для задачи."""
    current_phase = get_task_current_phase(jira_key)
    phase = schema.get_phase(current_phase)
    if not phase:
        phase = schema.Phase(id=current_phase, name="Unknown", description="Phase not found in schema")

    checklist = build_ui_checklist(phase)

    return templates.TemplateResponse(
        "wizard.html",
        {
            "request": request,
            "jira_key": jira_key,
            "phase": {
                "id": phase.id,
                "name": phase.name,
                "description": phase.description,
                "is_blocker": phase.is_blocker,
                "is_delegated": phase.is_delegated,
            },
            "checklist": checklist,
        },
    )


@app.post("/api/wizard/{jira_key}/answer")
def api_wizard_answer(
    jira_key: str,
    done_items: list[str] = Form(default_factory=list),
    notes: str = Form(default=""),
):
    """Принять ответ пользователя по wizard checklist."""
    current_phase = get_task_current_phase(jira_key)

    phase = schema.get_phase(current_phase)
    checklist = build_ui_checklist(phase) if phase else []
    total = len(checklist)
    done = len(done_items)

    ok = done > 0 or bool(notes.strip())
    conversation.add_wizard_answer(
        jira_key, jira_key, current_phase,
        json.dumps({"done": done_items, "notes": notes, "total": total, "date": datetime.datetime.now().isoformat()}, ensure_ascii=False),
        ok=ok,
    )

    if done >= total and total > 0:
        next_p = phases.get_next_phase(current_phase)
        if next_p:
            conversation.add_phase_transition(jira_key, jira_key, current_phase, next_p)
            repo = state.find_repo(jira_key) or ""
            state.save_state(repo, jira_key, jira_key, "", next_p)
        return {"ok": True, "status": "advanced", "next_phase": next_p, "done": done, "total": total}

    return {"ok": True, "status": "partial", "done": done, "total": total}

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
      <td><a href="/wizard/{{ t.jira_key }}">Wizard &rarr;</a> <a href="/task/{{ t.task_id }}">История &rarr;</a></td>
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


WIZARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wizard {{ jira_key }} — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Wizard: {{ jira_key }}</h2>
  <div class="card">
    <h2>Фаза {{ phase.id }} — {{ phase.name }}</h2>
    <p style="opacity:.7">{{ phase.description }}</p>
    {% if phase.is_blocker %}<span class="badge badge-block">BLOCKER</span>{% endif %}
    {% if phase.is_delegated %}<span class="badge badge-warn">DELEGATED</span>{% endif %}
  </div>

  <div class="card">
    <h2>📋 Чеклист ({{ checklist|length }} пунктов)</h2>
    <form id="wizardForm">
      {% for item in checklist %}
      <div style="margin:8px 0">
        <label>
          <input type="checkbox" name="done_items" value="{{ item.id }}"
                 data-type="{{ item.type }}">
          <span style="font-size:.9rem">{{ item.text }}</span>
        </label>
        {% if item.example %}<div style="margin-left:24px;font-size:.8rem;color:#94a3b8">{{ item.example }}</div>{% endif %}
        {% if item.command %}<div style="margin-left:24px;font-size:.8rem;color:#38bdf8;font-family:monospace">{{ item.command }}</div>{% endif %}
      </div>
      {% endfor %}

      <div style="margin-top:16px">
        <label style="display:block;margin-bottom:8px;font-size:.9rem">📝 Комментарий / заметки:</label>
        <textarea name="notes" style="width:100%;min-height:80px;background:#0b1220;color:var(--text);border:1px solid #334155;border-radius:4px;padding:8px;font-size:.9rem;"></textarea>
      </div>

      <div style="margin-top:16px;display:flex;gap:12px">
        <button type="submit" class="btn btn-primary">✅ Отправить</button>
        <button type="button" onclick="skipPhase()" class="btn btn-secondary">⏭ Пропустить</button>
      </div>
    </form>

    <div id="result" style="margin-top:16px;padding:12px;border-radius:4px;display:none;"></div>
  </div>

  <p><br><a href="/tasks">← Все задачи</a></p>
</div>

<style>
.btn{padding:10px 20px;border:none;border-radius:4px;font-size:.9rem;font-weight:600;cursor:pointer}
.btn-primary{background:var(--accent);color:#0f172a}
.btn-secondary{background:#334155;color:var(--text)}
#result.ok{background:rgba(34,197,94,.2);color:var(--ok)}
#result.warn{background:rgba(245,158,11,.2);color:var(--warn)}
input[type="checkbox"]{width:16px;height:16px;accent-color:var(--accent);margin-right:8px}
</style>

<script>
const form = document.getElementById('wizardForm');
const result = document.getElementById('result');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(form);
  const doneItems = formData.getAll('done_items');
  const notes = formData.get('notes') || '';

  if (doneItems.length === 0 && !notes) {
    result.textContent = '⚠️ Отметь хотя бы один пункт или оставь комментарий';
    result.className = 'warn';
    result.style.display = 'block';
    return;
  }

  const params = new URLSearchParams();
  params.append('notes', notes);
  doneItems.forEach(v => params.append('done_items', v));

  try {
    const resp = await fetch('/api/wizard/{{ jira_key }}/answer', {
      method: 'POST',
      body: params,
      headers: {'Content-Type': 'application/x-www-form-urlencoded'}
    });
    const data = await resp.json();

    if (data.status === 'advanced') {
      result.textContent = '✅ Все пункты выполнены! Переход к фазе ' + data.next_phase;
      result.className = 'ok';
      result.style.display = 'block';
      setTimeout(() => location.reload(), 2000);
    } else {
      result.textContent = `📊 Отмечено ${data.done || 0} из ${data.total || 0} пунктов`;
      result.className = 'warn';
      result.style.display = 'block';
    }
  } catch (err) {
    result.textContent = '❌ Ошибка: ' + err;
    result.className = 'warn';
    result.style.display = 'block';
  }
});

function skipPhase() {
  form.reset();
  result.textContent = '⏭ Фаза пропущена — переход к следующей';
  result.className = 'warn';
  result.style.display = 'block';
}
</script>
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
            "wizard.html": WIZARD_HTML,
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

            # Handle else (remove unused parts variable)
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
        "wizard.html": WIZARD_HTML,
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
