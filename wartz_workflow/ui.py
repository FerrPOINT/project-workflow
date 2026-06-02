"""Minimal Web UI for wartz-workflow — FastAPI + inline Jinja2-like templates.

Сервер на уникальном порту (default 8811):
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
import re
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
import uvicorn

from . import conversation, schema, config, state, phases, jobs, wizard

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = config.UI_PORT
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
DB_PATH = Path(config.WARTZ_DIR) / "conversation.db"

# ── FastAPI App ─────────────────────────────────────────────────────────
app = FastAPI(title="wartz-workflow UI", version="1.1.0")


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def load_phases() -> list[dict]:
    """Загрузить фазы из YAML."""
    try:
        plist = schema.load_phases()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "checks": [c.__dict__ for c in p.checks],
                "evidence": [e.__dict__ for e in p.evidence],
                "instructions": [i.__dict__ for i in p.instructions],
                "is_blocker": p.is_blocker,
                "is_delegated": p.is_delegated,
                "is_critic": p.is_critic,
                "gate_type": "blocker" if p.is_blocker else ("delegated" if p.is_delegated else "pass"),
                "rollback_target": p.rollback_target,
                "next_recommendation": p.next_recommendation,
                "parallel_with": p.parallel_with,
            }
            for p in plist
        ]
    except Exception:
        return []


def load_tasks() -> list[dict]:
    """Список задач из conversation.db."""
    if not DB_PATH.exists():
        return []
    rows = _get_all_messages_raw(limit=2000)
    tasks: dict[str, dict] = {}
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
        {**t, "phases": sorted(t["phases"])}
        for t in sorted(tasks.values(), key=lambda x: x["last_message"] or "", reverse=True)
    ]


def _get_all_messages_raw(limit: int = 2000) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM conversation ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
#  PAGES
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
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
    phases = load_phases()
    return templates.TemplateResponse(
        "phases.html",
        {"request": request, "phases": phases, "phase_order": config.PHASE_ORDER},
    )


@app.get("/phase/{phase_id}", response_class=HTMLResponse)
def phase_detail_page(request: Request, phase_id: str):
    phase = schema.get_phase(phase_id)
    if not phase:
        return _render_404(request, f"Phase {phase_id} not found")
    return templates.TemplateResponse(
        "phase_detail.html",
        {
            "request": request,
            "phase": {
                "id": phase.id,
                "name": phase.name,
                "description": phase.description,
                "is_blocker": phase.is_blocker,
                "is_delegated": phase.is_delegated,
                "is_critic": phase.is_critic,
                "skills": phase.skills,
                "checks": [c.__dict__ for c in phase.checks],
                "evidence": [e.__dict__ for e in phase.evidence],
                "instructions": [i.__dict__ for i in phase.instructions],
                "questions": [q.__dict__ for q in phase.questions],
                "delegate": phase.delegate.__dict__ if phase.delegate else None,
                "next_recommendation": phase.next_recommendation,
                "parallel_with": phase.parallel_with,
                "rollback_target": phase.rollback_target,
            },
            "phase_order": config.PHASE_ORDER,
        },
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    tasks = load_tasks()
    return templates.TemplateResponse(
        "tasks.html",
        {"request": request, "tasks": tasks},
    )


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: str):
    msgs = conversation.get_messages(task_id, limit=500) if DB_PATH.exists() else []
    return templates.TemplateResponse(
        "task.html",
        {"request": request, "task_id": task_id, "messages": msgs},
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    job_list = jobs.list_jobs()
    return templates.TemplateResponse(
        "jobs.html",
        {"request": request, "jobs": [j.__dict__ for j in job_list]},
    )


@app.get("/answers/{jira_key}", response_class=HTMLResponse)
def answers_page(request: Request, jira_key: str):
    msgs = conversation.get_messages(jira_key, limit=500) if DB_PATH.exists() else []
    answers = []
    for m in msgs:
        if m.role == "user" and m.tags in ("pass", "fail"):
            content = m.content
            try:
                data = json.loads(content)
            except Exception:
                data = {"raw": content}
            answers.append({
                "phase_id": m.phase_id or "-",
                "created_at": m.created_at,
                "ok": m.tags == "pass",
                "data": data,
            })
    return templates.TemplateResponse(
        "answers.html",
        {"request": request, "jira_key": jira_key, "answers": answers},
    )


@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
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
    msgs = conversation.get_messages(task_id, limit=500) if DB_PATH.exists() else []
    return {"ok": True, "task_id": task_id, "messages": [m.__dict__ for m in msgs]}


@app.get("/api/jobs")
def api_jobs(jira_key: str = "", phase_id: str = ""):
    job_list = jobs.list_jobs(jira_key=jira_key or None, phase_id=phase_id or None)
    return {"ok": True, "jobs": [j.__dict__ for j in job_list]}


@app.get("/api/jobs/{job_id}")
def api_job_detail(job_id: str):
    job = jobs.load_job(job_id)
    if not job:
        return {"ok": False, "error": "Job not found"}
    return {"ok": True, "job": job.__dict__}


@app.get("/api/answers/{jira_key}")
def api_answers(jira_key: str):
    msgs = conversation.get_messages(jira_key, limit=500) if DB_PATH.exists() else []
    answers = []
    for m in msgs:
        if m.role == "user" and m.tags in ("pass", "fail"):
            content = m.content
            try:
                data = json.loads(content)
            except Exception:
                data = {"raw": content}
            answers.append({
                "phase_id": m.phase_id or "-",
                "created_at": m.created_at,
                "ok": m.tags == "pass",
                "data": data,
            })
    return {"ok": True, "jira_key": jira_key, "answers": answers}


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
    ts = state.load_state(None, jira_key)
    if ts:
        return ts.get("current_phase", "-1")
    return conversation.get_last_phase(jira_key) or "-1"


def build_ui_checklist(phase: schema.Phase) -> list[dict]:
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
    """UI страница wizard — показывает текущую фазу и чеклист."""
    prompt = wizard.get_phase_instructions(jira_key)
    return templates.TemplateResponse(
        "wizard.html",
        {
            "request": request,
            "jira_key": jira_key,
            "prompt": prompt,
        },
    )


@app.post("/api/wizard/{jira_key}/answer")
def api_wizard_answer(
    jira_key: str,
    done_items: list[str] = Form(default_factory=list),
    notes: str = Form(default=""),
):
    """Агент прислал отчёт → вернуть verdict (PASS/FAIL) + инструкции."""
    report = "\n".join(done_items + [notes])
    result = wizard.evaluate_report(jira_key, report)

    # Save to conversation history
    conversation.add_wizard_answer(
        jira_key, jira_key, result["phase"],
        json.dumps(result, ensure_ascii=False),
        ok=(result["verdict"] == "PASS"),
    )

    return result


@app.get("/api/wizard/{jira_key}/instructions")
def api_wizard_instructions(jira_key: str):
    """Получить инструкции для текущей фазы (первое обращение агента)."""
    prompt = wizard.get_phase_instructions(jira_key)
    return {
        "ok": True,
        "jira_key": jira_key,
        "prompt": prompt,
    }


# ═══════════════════════════════════════════════════════════════════════
#  404 HELPER
# ═══════════════════════════════════════════════════════════════════════

def _render_404(request: Request, message: str):
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>404</title>{PAGE_STYLE}</head><body>
{HEADER_HTML}
<div class="container"><div class="card">
<h2>❌ {message}</h2>
<p><a href="/">← Dashboard</a></p>
</div></div></body></html>"""
    return HTMLResponse(html)


# ═══════════════════════════════════════════════════════════════════════
#  CLI ENTRY
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(prog="hrflow ui", description="Запустить веб-UI")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help=f"Порт (default {DEFAULT_UI_PORT})")
    parser.add_argument("--host", default="0.0.0.0", help="Хост (default 0.0.0.0)")
    parser.add_argument("--daemon", action="store_true", help="Запустить в background")
    args = parser.parse_args()
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
      <p><a href="/jobs">Background Jobs</a></p>
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
    <tr><th>#</th><th>ID</th><th>Name</th><th>Gate</th><th>Checks</th><th>Evidence</th><th></th></tr>
    {% for p in phases %}
    <tr>
      <td>{{ loop.index }}</td>
      <td class="phase-id">{{ p.id }}</td>
      <td class="phase-name">{{ p.name }}</td>
      <td><span class="badge {% if p.gate_type == 'blocker' %}badge-block{% endif %}">{{ p.gate_type }}</span></td>
      <td>{{ p.checks|length }}</td>
      <td>{{ p.evidence|length }}</td>
      <td><a href="/phase/{{ p.id }}">Детали &rarr;</a></td>
    </tr>
    {% endfor %}
  </table>
</div>
</body></html>"""

PHASE_DETAIL_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Phase {{ phase.id }} — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Фаза {{ phase.id }} — {{ phase.name }}</h2>
  <div class="card">
    <p>{{ phase.description }}</p>
    {% if phase.is_blocker %}<span class="badge badge-block">BLOCKER</span>{% endif %}
    {% if phase.is_delegated %}<span class="badge badge-warn">DELEGATED</span>{% endif %}
    {% if phase.is_critic %}<span class="badge badge-warn">CRITIC</span>{% endif %}
    {% if phase.skills %}<p><b>Skills:</b> {{ phase.skills|join(', ') }}</p>{% endif %}
    {% if phase.parallel_with %}<p><b>Parallel with:</b> {{ phase.parallel_with }}</p>{% endif %}
    {% if phase.rollback_target %}<p><b>Rollback target:</b> {{ phase.rollback_target }}</p>{% endif %}
    <p><b>Next:</b> {{ phase.next_recommendation or '—' }}</p>
  </div>

  {% if phase.instructions %}
  <div class="card">
    <h2>📋 Инструкции ({{ phase.instructions|length }})</h2>
    <table>
      <tr><th>#</th><th>Шаг</th><th>Tool</th><th>Пример</th></tr>
      {% for i in phase.instructions %}
      <tr><td>{{ loop.index }}</td><td>{{ i.step }}</td><td>{{ i.tool or '—' }}</td><td><code>{{ i.example or '—' }}</code></td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% if phase.checks %}
  <div class="card">
    <h2>🔍 Проверки ({{ phase.checks|length }})</h2>
    <table>
      <tr><th>#</th><th>Тип</th><th>Описание</th><th>Команда</th></tr>
      {% for c in phase.checks %}
      <tr><td>{{ loop.index }}</td><td><span class="badge">{{ c.type }}</span></td><td>{{ c.description }}</td><td><code>{{ c.command or '—' }}</code></td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% if phase.evidence %}
  <div class="card">
    <h2>📎 Evidence ({{ phase.evidence|length }})</h2>
    <table>
      <tr><th>#</th><th>Item</th><th>Валидатор</th></tr>
      {% for e in phase.evidence %}
      <tr><td>{{ loop.index }}</td><td>{{ e.item }}</td><td>{{ e.validator or '—' }}</td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% if phase.questions %}
  <div class="card">
    <h2>❓ Вопросы wizard ({{ phase.questions|length }})</h2>
    <table>
      <tr><th>#</th><th>Вопрос</th><th>Required</th><th>Keywords</th><th>Hint</th></tr>
      {% for q in phase.questions %}
      <tr><td>{{ loop.index }}</td><td>{{ q.text }}</td><td>{{ 'Yes' if q.required else 'No' }}</td><td>{{ q.expected_keywords|join(', ') or '—' }}</td><td>{{ q.hint or '—' }}</td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% if phase.delegate %}
  <div class="card">
    <h2>🤖 Делегирование</h2>
    <p><b>Агент:</b> {{ phase.delegate.agent }}</p>
    <p><b>Timeout:</b> {{ phase.delegate.timeout_min }} мин</p>
    <p><b>Max cycles:</b> {{ phase.delegate.max_cycles }}</p>
    {% if phase.delegate.toolsets %}<p><b>Toolsets:</b> {{ phase.delegate.toolsets|join(', ') }}</p>{% endif %}
  </div>
  {% endif %}

  <p><br><a href="/phases">← Все фазы</a></p>
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
      <td><a href="/wizard/{{ t.jira_key }}">Wizard &rarr;</a> <a href="/answers/{{ t.jira_key }}">Ответы &rarr;</a> <a href="/task/{{ t.task_id }}">История &rarr;</a></td>
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

JOBS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jobs — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Background Jobs ({{ jobs|length }})</h2>
  <table>
    <tr><th>Job ID</th><th>Jira Key</th><th>Phase</th><th>Agent</th><th>Status</th><th>Created</th></tr>
    {% for j in jobs %}
    <tr>
      <td><b>{{ j.job_id }}</b></td>
      <td>{{ j.jira_key }}</td>
      <td class="phase-id">{{ j.phase_id }}</td>
      <td>{{ j.agent }}</td>
      <td><span class="badge {% if j.status == 'complete' %}badge-ok{% elif j.status == 'failed' %}badge-block{% elif j.status == 'running' %}badge-warn{% endif %}">{{ j.status }}</span></td>
      <td>{{ j.created_at[:10] }}</td>
    </tr>
    {% endfor %}
  </table>
  <div class="card" style="margin-top:16px">
    <h2>API</h2>
    <p><code>GET /api/jobs?jira_key=XXX&amp;phase_id=YYY</code></p>
    <p><code>GET /api/jobs/&lt;job_id&gt;</code></p>
  </div>
</div>
</body></html>"""

ANSWERS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Answers {{ jira_key }} — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">Ответы wizard: {{ jira_key }}</h2>
  {% for a in answers %}
  <div class="card">
    <h3>Фаза {{ a.phase_id }} — {{ a.created_at[:16] }}</h3>
    <span class="badge {% if a.ok %}badge-ok{% else %}badge-block{% endif %}">{{ 'PASS' if a.ok else 'FAIL' }}</span>
    <pre>{{ a.data | tojson(indent=2) }}</pre>
  </div>
  {% else %}
  <p style="opacity:.6">Нет ответов. Используйте wizard или API.</p>
  {% endfor %}
  <p><br><a href="/tasks">← Все задачи</a></p>
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

WIZARD_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wizard {{ jira_key }} — wartz-workflow</title>
{{ style | safe }}</head>
<body>
{{ header | safe }}
<div class="container">
  <h2 style="margin-top:20px">🧙 Wizard: {{ jira_key }}</h2>

  <div class="card">
    <h3>📋 Инструкции по текущей фазе</h3>
    <pre style="white-space:pre-wrap;font-size:.9rem;line-height:1.6;background:#0b1220;padding:16px;border-radius:4px;border:1px solid #334155">{{ prompt }}</pre>
  </div>

  <div class="card">
    <h3>📝 Отчёт агента</h3>
    <p style="opacity:.7;font-size:.85rem">Опиши что выполнено по пунктам. Wizard проверит покрытие и вернёт verdict.</p>
    <form id="wizardForm">
      <textarea name="notes" style="width:100%;min-height:120px;background:#0b1220;color:var(--text);border:1px solid #334155;border-radius:4px;padding:8px;font-size:.9rem;" placeholder="Например: проверил пуллреквесты, воспроизвёл 2 бага, залогировал фазу..."></textarea>

      <div style="margin-top:16px;display:flex;gap:12px">
        <button type="submit" class="btn btn-primary">✅ Отправить отчёт</button>
      </div>
    </form>

    <div id="result" style="margin-top:16px;padding:16px;border-radius:4px;display:none;white-space:pre-wrap;font-size:.9rem"></div>
  </div>

  <p><br><a href="/answers/{{ jira_key }}">📊 История ответов &rarr;</a></p>
  <p><a href="/tasks">← Все задачи</a></p>
</div>

<style>
.btn{padding:10px 20px;border:none;border-radius:4px;font-size:.9rem;font-weight:600;cursor:pointer}
.btn-primary{background:var(--accent);color:#0f172a}
#result.ok{background:rgba(34,197,94,.2);color:var(--ok);border:1px solid var(--ok)}
#result.warn{background:rgba(245,158,11,.2);color:var(--warn);border:1px solid var(--warn)}
</style>

<script>
const form = document.getElementById('wizardForm');
const result = document.getElementById('result');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(form);
  const notes = formData.get('notes') || '';

  if (!notes.trim()) {
    result.textContent = '⚠️ Опиши что выполнено';
    result.className = 'warn';
    result.style.display = 'block';
    return;
  }

  const params = new URLSearchParams();
  params.append('notes', notes);

  try {
    const resp = await fetch('/api/wizard/{{ jira_key }}/answer', {
      method: 'POST',
      body: params,
      headers: {'Content-Type': 'application/x-www-form-urlencoded'}
    });
    const data = await resp.json();

    result.textContent = data.message || data.verdict;
    result.className = data.verdict === 'PASS' ? 'ok' : 'warn';
    result.style.display = 'block';

    if (data.verdict === 'PASS' && data.next_phase) {
      setTimeout(() => location.reload(), 3000);
    }
  } catch (err) {
    result.textContent = '❌ Ошибка: ' + err;
    result.className = 'warn';
    result.style.display = 'block';
  }
});
</script>
</body></html>"""

HEADER_HTML = """
<header>
  <h1>wartz-workflow UI</h1>
  <nav>
    <a href="/">Dashboard</a>
    <a href="/phases">Фазы</a>
    <a href="/tasks">Задачи</a>
    <a href="/jobs">Jobs</a>
    <a href="/config">Конфиг</a>
  </nav>
</header>
"""


class InlineTemplates:
    """Fallback рендер inline HTML."""

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
            "jobs.html": JOBS_HTML,
            "phase_detail.html": PHASE_DETAIL_HTML,
            "answers.html": ANSWERS_HTML,
        }
        tmpl = html_map.get(name, f"<!-- Template {name} not found -->")
        rendered = tmpl.replace("{{ style | safe }}", PAGE_STYLE)
        rendered = rendered.replace("{{ header | safe }}", HEADER_HTML)

        if "{% for" in rendered:
            return HTMLResponse(self._render_jinja_like(rendered, context))

        # Simple {{ var }} and {{ dict.key }} substitution
        rendered = self._substitute_vars(rendered, context)
        return HTMLResponse(rendered)

    def _substitute_vars(self, template: str, context: dict) -> str:
        result = template
        # Find all {{ ... }} patterns
        for match in re.finditer(r"\{\{\s*([^}]+)\s*\}\}", result):
            expr = match.group(1).strip()
            val = self._resolve_expr(expr, context)
            result = result.replace(match.group(0), str(val))
        return result

    def _resolve_expr(self, expr: str, context: dict) -> str:
        # Handle X or Y fallback
        if " or " in expr:
            parts = expr.split(" or ", 1)
            left = self._resolve_expr(parts[0].strip(), context)
            if left:
                return left
            right_raw = parts[1].strip()
            # Remove quotes from string literal
            if (right_raw.startswith("'") and right_raw.endswith("'")) or (right_raw.startswith('"') and right_raw.endswith('"')):
                return right_raw[1:-1]
            return self._resolve_expr(right_raw, context)

        # Handle Jinja2 filters:  x|length, x|join(', ')
        if "|" in expr:
            parts = expr.split("|", 1)
            base_expr = parts[0].strip()
            filter_expr = parts[1].strip()
            val = self._resolve_expr(base_expr, context)
            if "length" in filter_expr or "len" in filter_expr or "size" in filter_expr:
                try:
                    if isinstance(val, list):
                        return str(len(val))
                except Exception:
                    pass
                return str(len(str(val)))
            if "join" in filter_expr:
                m = re.search(r"join\(['\"](.+?)['\"]\)", filter_expr)
                sep = m.group(1) if m else ", "
                if isinstance(val, list):
                    return sep.join(str(v) for v in val)
                return str(val)
            if "tojson" in filter_expr or "json" in filter_expr:
                return json.dumps(val, ensure_ascii=False, indent=2) if isinstance(val, (dict, list)) else str(val)
            return str(val)

        parts = expr.split(".")
        val = context.get(parts[0], "")
        for part in parts[1:]:
            if isinstance(val, dict):
                val = val.get(part, "")
            elif isinstance(val, list) and part in ("length", "len", "size"):
                val = len(val)
            else:
                val = ""
        if isinstance(val, (list, dict)):
            return json.dumps(val, ensure_ascii=False, indent=2)
        if val is True:
            return "true"
        if val is False:
            return "false"
        if val is None:
            return ""
        return str(val)

    def _render_jinja_like(self, template: str, context: dict) -> str:
        result = template
        for key, val in context.items():
            if isinstance(val, str):
                result = result.replace(f"{{{{ {key} }}}}", val)

        for match in re.finditer(r"\{% for (\w+) in (\w+) %\}(.*?)\{% endfor %\}", result, re.S):
            var_name, list_name, body = match.groups()
            items = context.get(list_name, [])
            # Split body into main part and else part
            else_match = re.search(r"\{% else %\}(.*)$", body, flags=re.S)
            body_no_else = body[:else_match.start()] if else_match else body
            else_block = else_match.group(1) if else_match else ""
            if not items:
                result = result.replace(match.group(0), else_block)
                continue
            rendered_items = []
            for idx, item in enumerate(items):
                item_html = body_no_else
                # Convert {{ p.id }} → {{ id }} for simple substitution
                item_html = re.sub(r"\{\{\s*" + re.escape(var_name) + r"\.(\w+)\s*\}\}", r"{{ \1 }}", item_html)
                # Convert {{ p.checks|length }} → {{ checks|length }}
                item_html = re.sub(r"\{\{\s*" + re.escape(var_name) + r"\.(\w+)\|([^}]+)\s*\}\}", r"{{ \1|\2 }}", item_html)
                if isinstance(item, dict):
                    loop_ctx = dict(item)
                    loop_ctx["loop.index"] = idx + 1
                    item_html = self._substitute_vars(item_html, loop_ctx)
                rendered_items.append(item_html)
            full_match = match.group(0)
            result = result.replace(full_match, "".join(rendered_items))

        result = re.sub(r"\{% (if|for)[^%]*%\}", "", result)
        result = re.sub(r"\{% (endfor|endif) %\}", "", result)
        result = self._substitute_vars(result, context)
        return result


# ── Templates init ────────────────────────────────────────────────────

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
        "jobs.html": JOBS_HTML,
        "phase_detail.html": PHASE_DETAIL_HTML,
        "answers.html": ANSWERS_HTML,
    }
    for name, content in files.items():
        path = TEMPLATES_DIR / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


if not TEMPLATES_DIR.exists():
    templates = InlineTemplates()
else:
    templates = InlineTemplates()


if __name__ == "__main__":
    sys.exit(main())
