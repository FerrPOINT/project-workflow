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
    """Загрузить фазы из YAML с группировкой + flattened fields для рендерера."""
    _groups = {
        "setup": ["-1", "0.0a", "0.01", "0.01a", "0.01b", "0", "0.00", "0.000", "0.7", "0.9", "0.5"],
        "research": ["0.6", "1", "1.5", "2"],
        "plan": ["3", "3.5"],
        "implement": ["4", "4.5", "5", "5.5"],
        "deliver": ["6", "7", "7.5", "7.6", "7.6.R", "7.7"],
        "closure": ["8", "9", "10"],
    }
    _group_names = {
        "setup": "🚀 Подготовка",
        "research": "🔍 Исследование",
        "plan": "📐 Планирование",
        "implement": "💻 Реализация",
        "deliver": "📦 Поставка",
        "closure": "✅ Закрытие",
    }
    try:
        plist = schema.load_phases()
        _phase_order = config.PHASE_ORDER
        return [
            {
                "id": p.id,
                "phase_num": _phase_order.index(p.id) + 1 if p.id in _phase_order else 0,
                "name": p.name,
                "description": p.description,
                "checks": [c.__dict__ for c in p.checks],
                "evidence": [e.__dict__ for e in p.evidence],
                "instructions": [i.__dict__ for i in p.instructions],
                "is_blocker": p.is_blocker,
                "is_delegated": p.is_delegated,
                "is_critic": p.is_critic,
                "gate_type": "blocker" if p.is_blocker else ("delegated" if p.is_delegated else ("parallel" if p.parallel_with else "required")),
                "gate_badge_class": "badge-block" if p.is_blocker else ("badge-warn" if p.is_delegated else ("badge-accent" if p.parallel_with else "badge-ok")),
                "gate_label": "БЛОКЕР" if p.is_blocker else ("АГЕНТ" if p.is_delegated else ("ПАРАЛЛЕЛЬНО" if p.parallel_with else "")),
                "card_class": "blocker-left" if p.is_blocker else ("parallel-left" if p.parallel_with else ("delegated-left" if p.is_delegated else "")),
                "group": next((g for g, ids in _groups.items() if p.id in ids), "other"),
                "group_name": _group_names.get(next((g for g, ids in _groups.items() if p.id in ids), "other"), "Другое"),
                "rollback_target": p.rollback_target,
                "next_recommendation": p.next_recommendation,
                "parallel_with": p.parallel_with,
                "skills": p.skills,
                "questions": [q.__dict__ for q in p.questions],
                "delegate": p.delegate.__dict__ if p.delegate else None,
                "delegate_agent": p.delegate.agent if p.delegate else None,
                "delegate_timeout": p.delegate.timeout_min if p.delegate else None,
                "delegate_max_cycles": p.delegate.max_cycles if p.delegate else None,
                "delegate_toolsets": p.delegate.toolsets if p.delegate else None,
                "delegate_context": p.delegate.context if p.delegate else None,
                "delegate_prompt": p.delegate.prompt_template if p.delegate else None,
                "meta_extra": (
                    (f'<span>🤖 {p.delegate.agent}</span>' if p.delegate else '')
                    + (f'<span>⏸ {p.parallel_with}</span>' if p.parallel_with else '')
                ),
            }
            for p in plist
        ]
    except Exception:
        return []


def load_tasks() -> list[dict]:
    """Список задач из conversation.db — дедупликация по jira_key."""
    if not DB_PATH.exists():
        return []
    rows = _get_all_messages_raw(limit=2000)
    tasks: dict[str, dict] = {}
    for row in rows:
        jk = row.get("jira_key") or row.get("task_id", "unknown")
        if jk not in tasks:
            tasks[jk] = {
                "task_id": jk,
                "jira_key": jk,
                "message_count": 0,
                "last_message": None,
                "phases": set(),
            }
        tasks[jk]["message_count"] += 1
        if row.get("created_at"):
            tasks[jk]["last_message"] = max(tasks[jk]["last_message"] or row["created_at"], row["created_at"])
        if row.get("phase_id"):
            tasks[jk]["phases"].add(row["phase_id"])

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
    group_names = {
        "setup": "🚀 Подготовка",
        "research": "🔍 Исследование",
        "plan": "📐 Планирование",
        "implement": "💻 Реализация",
        "deliver": "📦 Поставка",
        "closure": "✅ Закрытие",
    }
    # Count real stats
    blocker_count = sum(1 for p in phases if p.get("gate_type") == "blocker")
    delegated_count = sum(1 for p in phases if p.get("gate_type") == "delegated")
    parallel_count = sum(1 for p in phases if p.get("parallel_with"))
    # Flatten with group headers inserted
    flat_phases: list[dict] = []
    current_group = None
    for p in phases:
        g = p.get("group", "other")
        if g != current_group and g in group_names:
            current_group = g
            cnt = sum(1 for ph in phases if ph.get("group") == g)
            suffix = "фаза" if cnt == 1 else ("фазы" if cnt < 5 else "фаз")
            flat_phases.append({"_is_header": True, "group_name": group_names[g], "group_key": g, "group_count": cnt, "group_count_suffix": suffix})
        flat_phases.append(p)
    return templates.TemplateResponse(
        "phases.html",
        {
            "request": request,
            "phases": phases,
            "flat_phases": flat_phases,
            "phase_count": len(phases),
            "blocker_count": blocker_count,
            "delegated_count": delegated_count,
            "parallel_count": parallel_count,
        },
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
                "delegate_agent": phase.delegate.agent if phase.delegate else None,
                "delegate_timeout": phase.delegate.timeout_min if phase.delegate else None,
                "delegate_max_cycles": phase.delegate.max_cycles if phase.delegate else None,
                "delegate_toolsets": phase.delegate.toolsets if phase.delegate else None,
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
        {"request": request, "task_id": task_id, "messages": [m.to_dict() for m in msgs]},
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
    return {"ok": True, "task_id": task_id, "messages": [m.to_dict() for m in msgs]}


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
:root{--bg:#0a0e1a;--card:#111827;--card-hover:#1a2234;--text:#e2e8f0;--text-muted:#64748b;--accent:#38bdf8;--accent-dim:#0ea5e9;--ok:#22c55e;--ok-dim:#16a34a;--warn:#f59e0b;--warn-dim:#d97706;--bad:#ef4444;--bad-dim:#dc2626;--border:#1e293b;}
*{box-sizing:border-box;font-family:'Inter',system-ui,-apple-system,sans-serif}
body{background:var(--bg);color:var(--text);margin:0;padding:0;line-height:1.5}
.container{max-width:1400px;margin:0 auto;padding:20px}
header{background:var(--card);padding:0 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;height:56px;position:sticky;top:0;z-index:100}
header h1{margin:0;font-size:1.1rem;color:var(--accent);font-weight:700;letter-spacing:.02em}
nav a{color:var(--text-muted);text-decoration:none;margin-left:24px;font-size:.85rem;font-weight:500;transition:color .15s;padding:4px 0;border-bottom:2px solid transparent}
nav a:hover,nav a.active{color:var(--accent);border-bottom-color:var(--accent)}
h2{margin:24px 0 12px;font-size:1.3rem;font-weight:700;color:var(--text)}
h3{margin:16px 0 8px;font-size:1rem;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em}

/* Cards */
.card{background:var(--card);border-radius:12px;padding:20px;margin-bottom:16px;border:1px solid var(--border);transition:background .15s,transform .1s}
.card:hover{background:var(--card-hover)}
.card-compact{padding:14px 18px;margin-bottom:10px}
.card h2{margin-top:0;color:var(--accent);font-size:1.05rem;font-weight:600}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:12px;flex-wrap:wrap}
.card-title{font-size:1.05rem;font-weight:600;color:var(--text)}
.card-subtitle{font-size:.8rem;color:var(--text-muted);margin-top:2px}

/* Badges */
.badge{display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;gap:4px;border:1px solid transparent}
.badge-ok{background:rgba(34,197,94,.12);color:var(--ok);border-color:rgba(34,197,94,.25)}
.badge-warn{background:rgba(245,158,11,.12);color:var(--warn);border-color:rgba(245,158,11,.25)}
.badge-block{background:rgba(239,68,68,.12);color:var(--bad);border-color:rgba(239,68,68,.25)}
.badge-accent{background:rgba(99,102,241,.12);color:var(--accent);border-color:rgba(99,102,241,.25)}

/* Stats bar */
.stats-bar{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.stat-item{background:var(--card);border-radius:10px;padding:14px 18px;border:1px solid var(--border);min-width:140px;flex:1}
.stat-value{font-size:1.6rem;font-weight:800;color:var(--accent);line-height:1}
.stat-label{font-size:.75rem;color:var(--text-muted);margin-top:4px;text-transform:uppercase;letter-spacing:.05em}

/* Phase group */
.phase-group{margin-bottom:32px}
.phase-group-header{display:flex;align-items:center;gap:10px;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.phase-group-title{font-size:1.1rem;font-weight:700;color:var(--text)}
.phase-group-count{font-size:.75rem;color:var(--text-muted);background:var(--card);padding:2px 8px;border-radius:10px;border:1px solid var(--border)}
.phase-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}

/* Phase card */
.phase-card{background:var(--card);border-radius:10px;padding:14px 16px;border:1px solid var(--border);display:flex;flex-direction:column;gap:10px;cursor:pointer;text-decoration:none;color:inherit;transition:all .15s;position:relative;overflow:hidden}
.phase-card:hover{border-color:var(--accent);background:var(--card-hover);transform:translateY(-1px)}
.phase-card.blocker-left{border-left:3px solid var(--bad)}
.phase-card.delegated-left{border-left:3px solid var(--warn)}
.phase-card.parallel-left{border-left:3px solid var(--accent)}
.phase-card-header{display:flex;justify-content:space-between;align-items:center;gap:8px}
.phase-card-id{font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--text-muted);font-weight:600}
.phase-card-num{font-size:.7rem;color:var(--text-muted);background:rgba(100,116,139,.15);padding:1px 6px;border-radius:10px}
.phase-card-name{font-size:.9rem;font-weight:600;color:var(--text)}
.phase-card-meta{display:flex;gap:12px;font-size:.75rem;color:var(--text-muted);align-items:center;flex-wrap:wrap}
.phase-card-meta span{display:inline-flex;align-items:center;gap:3px}

/* Tables */
table{width:100%;border-collapse:separate;border-spacing:0;margin-top:8px}
th{background:var(--card);padding:10px 12px;text-align:left;font-size:.72rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border);position:sticky;top:56px;z-index:90}
td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);font-size:.85rem;vertical-align:top}
tr:hover td{background:rgba(56,189,248,.03)}
pre{background:#060a14;padding:12px;border-radius:6px;overflow:auto;font-size:.8rem;border:1px solid var(--border);color:var(--text-muted)}
code{background:#060a14;padding:2px 6px;border-radius:4px;font-size:.8rem;border:1px solid var(--border);color:var(--accent)}

/* Checklist */
.checklist{display:flex;flex-direction:column;gap:8px}
.check-item{display:flex;gap:10px;align-items:start;padding:8px 10px;border-radius:6px;transition:background .1s}
.check-item:hover{background:rgba(56,189,248,.04)}
.check-icon{width:20px;height:20px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:.75rem;flex-shrink:0;margin-top:1px}
.check-icon.ok{background:rgba(34,197,94,.15);color:var(--ok)}
.check-icon.block{background:rgba(239,68,68,.15);color:var(--bad)}
.check-icon.warn{background:rgba(245,158,11,.15);color:var(--warn)}
.check-text{flex:1;font-size:.85rem}
.check-text code{font-size:.75rem;margin-left:4px}

/* Buttons */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border:none;border-radius:6px;font-size:.8rem;font-weight:600;cursor:pointer;transition:all .15s;text-decoration:none}
.btn-primary{background:var(--accent);color:#0a0e1a}
.btn-primary:hover{background:var(--accent-dim)}
.btn-ghost{background:transparent;color:var(--text-muted);border:1px solid var(--border)}
.btn-ghost:hover{background:var(--card-hover);color:var(--text)}

/* Filters */
.filter-bar{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;align-items:center}
.filter-btn{padding:6px 14px;border-radius:20px;border:1px solid var(--border);background:var(--card);color:var(--text-muted);font-size:.8rem;cursor:pointer;transition:all .15s}
.filter-btn:hover,.filter-btn.active{border-color:var(--accent);color:var(--accent);background:rgba(56,189,248,.08)}
.search-input{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 14px;color:var(--text);font-size:.85rem;min-width:240px;outline:none}
.search-input:focus{border-color:var(--accent)}

/* Wizard */
.wizard-prompt{background:#060a14;padding:20px;border-radius:10px;border:1px solid var(--border);font-size:.85rem;line-height:1.7;white-space:pre-wrap;max-height:500px;overflow:auto}
.wizard-form textarea{width:100%;min-height:140px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:.85rem;outline:none;resize:vertical}
.wizard-form textarea:focus{border-color:var(--accent)}

/* Timeline */
.timeline{display:flex;gap:4px;margin:16px 0;flex-wrap:wrap}
.timeline-dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.timeline-dot.pass{background:var(--ok)}
.timeline-dot.blocker{background:var(--bad)}
.timeline-dot.delegated{background:var(--warn)}
.timeline-dot.pending{background:var(--text-muted)}

/* Misc */
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.empty-state{text-align:center;padding:40px;color:var(--text-muted);font-size:.9rem}
.divider{height:1px;background:var(--border);margin:16px 0}
::-webkit-scrollbar{width:8px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:var(--text-muted)}
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
      <p><b>Блокеров:</b> {{ blocker_count }}</p>
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
  <div class="stats-bar">
    <div class="stat-item"><div class="stat-value">{{ phases|length }}</div><div class="stat-label">Всего фаз</div></div>
    <div class="stat-item"><div class="stat-value" style="color:var(--bad)">{{ blocker_count }}</div><div class="stat-label">Блокеры</div></div>
    <div class="stat-item"><div class="stat-value" style="color:var(--warn)">{{ delegated_count }}</div><div class="stat-label">На агентах</div></div>
    <div class="stat-item"><div class="stat-value" style="color:var(--accent)">{{ parallel_count }}</div><div class="stat-label">Параллельные</div></div>
  </div>

  <!-- Timeline -->
  <div class="card card-compact">
    <div class="card-header">
      <span class="card-title">Pipeline timeline</span>
      <span class="card-subtitle">Каждая точка = фаза. Цвет = тип gate.</span>
    </div>
    <div class="timeline">
      {% for p in phases %}
        <span class="timeline-dot {{ p.gate_type }}" title="{{ p.id }} — {{ p.name }}"></span>
      {% endfor %}
    </div>
  </div>

  <!-- Flat phases with inline group headers (no nested loops) -->
  <div class="phase-grid">
    {% for item in flat_phases %}
      {% if item._is_header %}
        <div class="phase-group" style="grid-column:1/-1">
          <div class="phase-group-header">
            <span class="phase-group-title">{{ item.group_name }}</span>
            <span class="phase-group-count">{{ item.group_count }} {{ item.group_count_suffix }}</span>
          </div>
        </div>
      {% endif %}
      {% if item.id %}
        <a class="phase-card {{ item.card_class }}" href="/phase/{{ item.id }}">
          <div class="phase-card-header">
            <span class="phase-card-id">{{ item.id }}</span>
            <span class="phase-card-num">№{{ item.phase_num }}</span>
            <span class="badge {{ item.gate_badge_class }}">{{ item.gate_label }}</span>
          </div>
          <div class="phase-card-name">{{ item.name }}</div>
          <div class="phase-card-meta">
            <span>🔍 {{ item.checks|length }}</span>
            <span>📎 {{ item.evidence|length }}</span>
            {{ item.meta_extra | safe }}
          </div>
        </a>
      {% endif %}
    {% endfor %}
  </div>
</div>

<script>
  document.querySelector('nav a[href="/phases"]').classList.add('active');
</script>
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
      <tr><td>{{ loop.index }}</td><td>{{ q.text }}</td><td>{% if q.required %}Yes{% else %}No{% endif %}</td><td>{{ q.expected_keywords|join(', ') or '—' }}</td><td>{{ q.hint or '—' }}</td></tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% if phase.delegate %}
  <div class="card">
    <h2>🤖 Делегирование</h2>
    <p><b>Агент:</b> {{ phase.delegate_agent }}</p>
    <p><b>Timeout:</b> {{ phase.delegate_timeout }} мин</p>
    <p><b>Max cycles:</b> {{ phase.delegate_max_cycles }}</p>
    {% if phase.delegate_toolsets %}<p><b>Toolsets:</b> {{ phase.delegate_toolsets|join(', ') }}</p>{% endif %}
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
      <td><span class="badge {% if j.status == 'complete' %}badge-ok{% endif %}{% if j.status == 'failed' %}badge-block{% endif %}{% if j.status == 'running' %}badge-warn{% endif %}">{{ j.status }}</span></td>
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
    <span class="badge {% if a.ok %}badge-ok{% else %}badge-block{% endif %}">{% if a.ok %}PASS{% else %}FAIL{% endif %}</span>
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
                    # If val is a string that looks like JSON list, try to parse
                    if isinstance(val, str):
                        try:
                            parsed = json.loads(val)
                            if isinstance(parsed, list):
                                return str(len(parsed))
                        except Exception:
                            pass
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

    def _split_for_else(self, body: str) -> tuple[str, str]:
        """Split for-loop body into main + else, ignoring {% else %} inside nested {% if %}.
        Strategy: remove all {% if %}...{% endif %} blocks first, then find top-level {% else %}.
        """
        # Remove nested if blocks to find top-level else
        stripped = body
        while True:
            m = re.search(r"\{%\s*if[^%]*%\}.*?\{%\s*endif\s*%\}", stripped, re.S)
            if not m:
                break
            stripped = stripped[:m.start()] + "__IFBLOCK__" + stripped[m.end():]
        else_match = re.search(r"\{%\s*else\s*%\}", stripped, flags=re.S)
        if not else_match:
            return body, ""
        # Map position back to original body: skip __IFBLOCK__ placeholders
        pos_in_stripped = else_match.start()
        pos_in_original = 0
        placeholder_count = 0
        for m in re.finditer(r"__IFBLOCK__", stripped):
            if m.start() < pos_in_stripped:
                placeholder_count += 1
        # Find corresponding else position in original body by skipping placeholder_count if-blocks
        idx = 0
        for _ in range(placeholder_count + 1):
            m = re.search(r"\{%\s*else\s*%\}", body[idx:], flags=re.S)
            if not m:
                break
            idx += m.start()
        # Now idx is the start of the correct else
        else_in_orig = re.search(r"\{%\s*else\s*%\}", body[idx:], flags=re.S)
        if else_in_orig:
            actual_pos = idx + else_in_orig.start()
            return body[:actual_pos], body[actual_pos + len(else_in_orig.group(0)):]
        return body, ""

    def _render_jinja_like(self, template: str, context: dict) -> str:
        result = template
        for key, val in context.items():
            if isinstance(val, str):
                result = result.replace(f"{{{{ {key} }}}}", val)

        # ── for loops ──────────────────────────────────────────────────
        for match in re.finditer(r"\{% for (\w+) in ([\w.]+) %\}(.*?)\{% endfor %\}", result, re.S):
            var_name, list_expr, body = match.groups()
            items = self._resolve_expr(list_expr, context)
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []
            if not isinstance(items, list):
                items = []
            # Split body into main part and else part — respect nested {% if %}
            body_no_else, else_block = self._split_for_else(body)
            if not items:
                result = result.replace(match.group(0), else_block)
                continue
            rendered_items = []
            for idx, item in enumerate(items):
                item_html = body_no_else
                # Replace dot notation with fallback: {{ i.tool or '—' }} → {{ tool or '—' }}
                item_html = re.sub(
                    r"\{\{\s*" + re.escape(var_name) + r"\.(\w+)\s+or\s+['\"]([^'\"]+)['\"]\s*\}\}",
                    r"{{ \1 or '\2' }}", item_html
                )
                # Replace dot notation references: {{ i.step }} → {{ step }}
                item_html = re.sub(
                    r"\{\{\s*" + re.escape(var_name) + r"\.(\w+)\s*\}\}",
                    r"{{ \1 }}", item_html
                )
                # Replace dot notation with filters: {{ i.tool|length }} → {{ tool|length }}
                item_html = re.sub(
                    r"\{\{\s*" + re.escape(var_name) + r"\.(\w+)\s*\|([^}]+)\s*\}\}",
                    r"{{ \1|\2 }}", item_html
                )
                # Replace if conditions: {% if i.tool %} → {% if tool %}
                item_html = re.sub(
                    r"\{%\s*if\s+" + re.escape(var_name) + r"\.(\w+)\s*([=!><]+)\s*['\"]([^'\"]+)['\"]\s*%\}",
                    r"{% if \1 \2 '\3' %}", item_html
                )
                item_html = re.sub(
                    r"\{%\s*if\s+" + re.escape(var_name) + r"\.(\w+)\s*%\}",
                    r"{% if \1 %}", item_html
                )
                if isinstance(item, dict):
                    loop_ctx = dict(item)
                    loop_ctx["loop"] = {"index": idx + 1, "index0": idx}
                    # Process nested {% if %} blocks
                    while True:
                        match_if = re.search(r"\{%\s*if\s+([^%]+)\s*%\}(.*?)\{%\s*endif\s*%\}", item_html, re.S)
                        if not match_if:
                            break
                        condition = match_if.group(1).strip()
                        content = match_if.group(2)
                        # Split into if/else
                        else_m = re.search(r"\{%\s*else\s*%\}", content)
                        if else_m:
                            if_content = content[:else_m.start()]
                            else_content = content[else_m.end():]
                        else:
                            if_content = content
                            else_content = ""
                        # Simple condition: just key name or key == 'value'
                        eq_match = re.match(r"^(\w+)\s*==\s*['\"]([^'\"]+)['\"]$", condition)
                        if eq_match:
                            key, expected = eq_match.groups()
                            cond_val = loop_ctx.get(key, "") == expected
                        else:
                            cond_val = loop_ctx.get(condition, False)
                            if isinstance(cond_val, str):
                                cond_val = bool(cond_val.strip())
                        if cond_val:
                            item_html = item_html[:match_if.start()] + if_content + item_html[match_if.end():]
                        else:
                            item_html = item_html[:match_if.start()] + else_content + item_html[match_if.end():]
                    item_html = self._substitute_vars(item_html, loop_ctx)
                else:
                    # Simple list of strings
                    item_html = self._substitute_vars(item_html, {"loop": {"index": idx + 1}, "item": item})
                rendered_items.append(item_html)
            full_match = match.group(0)
            result = result.replace(full_match, "".join(rendered_items))

        # Process top-level {% if %} blocks
        while True:
            match = re.search(r"\{%\s*if\s+([^%]+)\s*%\}(.*?)\{%\s*endif\s*%\}", result, re.S)
            if not match:
                break
            condition = match.group(1).strip()
            content = match.group(2)
            # Split into if/else
            else_m = re.search(r"\{%\s*else\s*%\}", content)
            if else_m:
                if_content = content[:else_m.start()]
                else_content = content[else_m.end():]
            else:
                if_content = content
                else_content = ""
            # Handle X == 'value'
            eq_match = re.match(r"^(\w+)\s*==\s*['\"]([^'\"]+)['\"]$", condition)
            if eq_match:
                key, expected = eq_match.groups()
                cond_val = context.get(key, "") == expected
            else:
                parts = condition.split(".")
                cond_val = context.get(parts[0], "")
                for part in parts[1:]:
                    if isinstance(cond_val, dict):
                        cond_val = cond_val.get(part, False)
                    else:
                        cond_val = False
                        break
            if cond_val:
                result = result[:match.start()] + if_content + result[match.end():]
            else:
                result = result[:match.start()] + else_content + result[match.end():]

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
