"""WARTZ Workflow UI — Linear-style phases viewer.

Сервер:
    python -m wartz_workflow.ui [--port N]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn

from . import schema, config

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = config.UI_PORT
BASE_DIR = Path(__file__).parent

app = FastAPI(title="wartz-workflow UI", version="1.3.0")


# ═══════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════

def load_phases() -> list[dict]:
    """Загрузить фазы из YAML с метаданными."""
    try:
        plist = schema.load_phases()
        _phase_order = config.PHASE_ORDER
        result = []
        for p in plist:
            result.append(
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
                    "gate_label": "БЛОКЕР" if p.is_blocker else ("АГЕНТ" if p.is_delegated else ""),
                    "skills": p.skills,
                    "delegate_agent": p.delegate.agent if p.delegate else None,
                    "delegate_timeout": p.delegate.timeout_min if p.delegate else None,
                    "rollback_target": p.rollback_target,
                    "next_recommendation": p.next_recommendation,
                    "parallel_with": p.parallel_with,
                }
            )
        return result
    except Exception:
        return []


def _escape_html(text: str) -> str:
    if text is None:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_phases_list(phases: list[dict]) -> str:
    lines = []
    for p in phases:
        badge = ""
        if p.get("gate_label"):
            cls = "badge-block" if p.get("is_blocker") else "badge-warn"
            badge = f'<span class="badge {cls}">{_escape_html(p["gate_label"])}</span>'
        desc = f'<div class="phase-desc">{_escape_html(p["description"] or "")}</div>' if p.get("description") else ""
        lines.append(
            f'    <a class="phase-row" href="/phase/{p["id"]}">\n'
            f'      <div class="phase-num">№{p["phase_num"]}</div>\n'
            f'      <div>\n'
            f'        <div class="phase-name">{_escape_html(p["name"])}</div>\n'
            f'        {desc}\n'
            f'      </div>\n'
            f'      <div class="phase-badges">{badge}</div>\n'
            f'    </a>'
        )
    return "\n".join(lines)


def _render_instructions(instructions: list[dict], is_delegated: bool) -> str:
    if not instructions:
        return '<div class="detail-card empty">Нет инструкций.</div>'
    lines = []
    for idx, i in enumerate(instructions, 1):
        tool = i.get("tool", "")
        tool_html = f'<span style="color:var(--accent)">{_escape_html(tool)}</span> ' if tool else ""
        sync = "async" if is_delegated else "sync"
        step = i.get("step", "")
        lines.append(
            f'    <div class="instruction">\n'
            f'      <div class="instruction-num">{idx}</div>\n'
            f'      <div class="instruction-text">{_escape_html(step)}</div>\n'
            f'      <div class="instruction-tool">{tool_html}<span class="{sync}">{sync}</span></div>\n'
            f'    </div>'
        )
    return "\n".join(lines)


def _render_checks(checks: list[dict]) -> str:
    if not checks:
        return '<div class="detail-card empty">Нет проверок.</div>'
    rows = []
    for idx, c in enumerate(checks, 1):
        rows.append(
            f"      <tr><td>{idx}</td><td><code>{_escape_html(c.get('type', ''))}</code></td>"
            f"<td>{_escape_html(c.get('description', ''))}</td></tr>"
        )
    return (
        '    <table>\n'
        '      <tr><th>#</th><th>Тип</th><th>Описание</th></tr>\n'
        + "\n".join(rows) +
        '\n    </table>'
    )


def _render_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return '<div class="detail-card empty">Нет evidence.</div>'
    rows = []
    for idx, e in enumerate(evidence, 1):
        rows.append(
            f"      <tr><td>{idx}</td><td>{_escape_html(e.get('item', ''))}</td>"
            f"<td>{_escape_html(e.get('validator', '—'))}</td></tr>"
        )
    return (
        '    <table>\n'
        '      <tr><th>#</th><th>Что собрать</th><th>Валидатор</th></tr>\n'
        + "\n".join(rows) +
        '\n    </table>'
    )


def _render_phase_detail_content(phase: dict) -> str:
    """Генерирует весь HTML контента для страницы детали фазы."""
    parts = []

    # Header
    badge = ""
    if phase.get("gate_label"):
        cls = "badge-block" if phase.get("is_blocker") else "badge-warn"
        badge = f'<span class="badge {cls}">{_escape_html(phase["gate_label"])}</span>'

    desc_html = f'<p style="color:var(--text-muted);font-size:14px;margin-top:4px">{_escape_html(phase["description"] or "")}</p>' if phase.get("description") else ""

    meta_parts = []
    if phase.get("skills"):
        skills_str = ", ".join(str(s) for s in phase["skills"])
        meta_parts.append(f'<span><b>Skills:</b> {_escape_html(skills_str)}</span>')
    if phase.get("delegate_agent"):
        timeout = phase.get("delegate_timeout", "—")
        meta_parts.append(f'<span><b>Агент:</b> {_escape_html(phase["delegate_agent"])} ({timeout} мин)</span>')
    if phase.get("parallel_with"):
        meta_parts.append(f'<span><b>Параллельно с:</b> {_escape_html(phase["parallel_with"])}</span>')
    if phase.get("rollback_target"):
        meta_parts.append(f'<span><b>Откат:</b> {_escape_html(phase["rollback_target"])}</span>')
    if phase.get("next_recommendation"):
        meta_parts.append(f'<span><b>Следующая:</b> {_escape_html(phase["next_recommendation"])}</span>')

    meta_html = ""
    if meta_parts:
        meta_html = '<div class="meta">' + " ".join(meta_parts) + "</div>"

    parts.append(
        f'  <a href="/phases" class="back-link">← Все фазы</a>\n'
        f'  <div class="phase-detail-header">\n'
        f'    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">\n'
        f'      <span style="font-family:\'JetBrains Mono\',monospace;font-size:12px;color:var(--text-dim)">№{phase["phase_num"]}</span>\n'
        f'      <h2>{_escape_html(phase["name"])}</h2>\n'
        f'      {badge}\n'
        f'    </div>\n'
        f'    {desc_html}\n'
        f'    {meta_html}\n'
        f'  </div>'
    )

    # Instructions
    instructions = phase.get("instructions", [])
    if instructions:
        parts.append(
            f'  <div class="detail-card">\n'
            f'    <h3>Инструкции ({len(instructions)})</h3>\n'
            f'{_render_instructions(instructions, phase.get("is_delegated", False))}\n'
            f'  </div>'
        )

    # Checks
    checks = phase.get("checks", [])
    parts.append(
        f'  <div class="detail-card">\n'
        f'    <h3>Проверки ({len(checks)})</h3>\n'
        f'{_render_checks(checks)}\n'
        f'  </div>'
    )

    # Evidence
    evidence = phase.get("evidence", [])
    parts.append(
        f'  <div class="detail-card">\n'
        f'    <h3>Evidence ({len(evidence)})</h3>\n'
        f'{_render_evidence(evidence)}\n'
        f'  </div>'
    )

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
#  STYLES
# ═══════════════════════════════════════════════════════════════════════

PAGE_STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root{
  --bg:#08090a;--panel:#0f1011;--surface:#191a1b;--surface-hover:#1f2022;
  --text:#f7f8f8;--text-secondary:#d0d6e0;--text-muted:#8a8f98;--text-dim:#62666d;
  --accent:#5e6ad2;--accent-hover:#828fff;--border:rgba(255,255,255,0.06);--border-strong:rgba(255,255,255,0.10);
}
*{box-sizing:border-box;margin:0;padding:0}
html{font-feature-settings:"cv01","ss03"}
body{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,-apple-system,sans-serif;line-height:1.5;font-size:14px}
.container{max-width:1200px;margin:0 auto;padding:24px}

/* Header */
header{background:var(--panel);border-bottom:1px solid var(--border);padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
header h1{font-size:15px;font-weight:600;color:var(--text);letter-spacing:-0.2px}
header h1 span{color:var(--accent);font-weight:700}
nav a{color:var(--text-muted);text-decoration:none;margin-left:24px;font-size:13px;font-weight:500;transition:color .15s;padding:4px 0;border-bottom:2px solid transparent}
nav a:hover,nav a.active{color:var(--text);border-bottom-color:var(--accent)}

/* Headings */
h2{font-size:24px;font-weight:500;color:var(--text);letter-spacing:-0.3px;margin:0 0 20px}
h3{font-size:14px;font-weight:600;color:var(--text-secondary);margin:0 0 12px;text-transform:uppercase;letter-spacing:0.06em}

/* Badges */
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;border:1px solid transparent;white-space:nowrap}
.badge-block{background:rgba(239,68,68,.12);color:#ef4444;border-color:rgba(239,68,68,.25)}
.badge-warn{background:rgba(245,158,11,.12);color:#f59e0b;border-color:rgba(245,158,11,.25)}

/* Phase list */
.phase-list{display:flex;flex-direction:column;gap:1px;background:var(--border);border-radius:8px;overflow:hidden;border:1px solid var(--border);margin-top:20px}
.phase-row{background:var(--surface);padding:14px 18px;display:grid;grid-template-columns:56px 1fr auto;gap:16px;align-items:center;transition:background .1s;cursor:pointer;text-decoration:none;color:inherit}
.phase-row:hover{background:var(--surface-hover)}
.phase-num{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:500;color:var(--text-dim);text-align:center}
.phase-name{font-size:14px;font-weight:500;color:var(--text);letter-spacing:-0.12px}
.phase-desc{font-size:12px;color:var(--text-muted);margin-top:2px;letter-spacing:-0.1px}
.phase-badges{display:flex;gap:6px;align-items:center}

/* Phase detail */
.phase-detail-header{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px 24px;margin-bottom:16px}
.phase-detail-header h2{margin:0;font-size:20px;font-weight:500;letter-spacing:-0.25px;display:inline}
.phase-detail-header .meta{display:flex;gap:12px;margin-top:12px;flex-wrap:wrap}
.phase-detail-header .meta span{color:var(--text-muted);font-size:12px}
.phase-detail-header .meta span b{color:var(--text-secondary);font-weight:500}

.detail-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 20px;margin-bottom:12px}
.detail-card.empty{color:var(--text-dim);font-size:13px;padding:24px 20px}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th{text-align:left;padding:8px 12px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;border-bottom:1px solid var(--border-strong);background:var(--panel)}
td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text-secondary);vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}

/* Code */
code{background:rgba(255,255,255,.04);padding:2px 6px;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-secondary);border:1px solid var(--border)}

/* Instructions */
.instruction{display:grid;grid-template-columns:28px 1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid var(--border);align-items:start}
.instruction:last-child{border-bottom:none}
.instruction-num{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-dim);padding-top:2px}
.instruction-text{font-size:13px;color:var(--text-secondary);line-height:1.5}
.instruction-tool{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;white-space:nowrap;text-align:right}
.instruction-tool .sync{color:var(--text-muted)}
.instruction-tool .async{color:var(--accent)}

/* Back link */
.back-link{display:inline-flex;align-items:center;gap:6px;color:var(--text-muted);text-decoration:none;font-size:13px;font-weight:500;margin-bottom:16px;transition:color .15s}
.back-link:hover{color:var(--text)}

/* Links */
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
</style>
"""

HEADER_HTML = """
<header>
  <h1>wartz<span style="color:var(--accent)">workflow</span></h1>
  <nav>
    <a href="/phases">Фазы</a>
  </nav>
</header>
"""


# ═══════════════════════════════════════════════════════════════════════
#  RENDERER
# ═══════════════════════════════════════════════════════════════════════

def _render_template(template: str, context: dict) -> str:
    """Простой рендер: заменяет {{ key }} на значение из контекста."""
    result = template
    # Заменяем safe-фильтры
    result = result.replace("{{ style | safe }}", PAGE_STYLE)
    result = result.replace("{{ header | safe }}", HEADER_HTML)
    # Заменяем простые переменные
    for key, val in context.items():
        if isinstance(val, str):
            result = result.replace(f"{{{{ {key} | safe }}}}", val)
            result = result.replace(f"{{{{ {key} }}}}", val)
    return result


def TemplateResponse(name: str, context: dict) -> HTMLResponse:
    """Загружает шаблон из файла и рендерит."""
    template_path = BASE_DIR / "templates" / name
    if not template_path.exists():
        return HTMLResponse(f"<!-- Template {name} not found -->", status_code=500)
    template = template_path.read_text(encoding="utf-8")
    rendered = _render_template(template, context)
    return HTMLResponse(rendered)


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return TemplateResponse("index.html", {"request": request})


@app.get("/phases", response_class=HTMLResponse)
def phases_page(request: Request):
    phases = load_phases()
    return TemplateResponse(
        "phases.html",
        {
            "request": request,
            "phases_html": _render_phases_list(phases),
        },
    )


@app.get("/phase/{phase_id}", response_class=HTMLResponse)
def phase_detail(request: Request, phase_id: str):
    phases = load_phases()
    phase = next((p for p in phases if p["id"] == phase_id), None)
    if not phase:
        return HTMLResponse("<h1>Phase not found</h1>", status_code=404)
    return TemplateResponse(
        "phase_detail.html",
        {
            "request": request,
            "phase_id": phase_id,
            "content_html": _render_phase_detail_content(phase),
        },
    )


@app.get("/api/phases")
def api_phases():
    return {"ok": True, "phases": load_phases()}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="WARTZ Workflow UI")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: %(default)s)")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
