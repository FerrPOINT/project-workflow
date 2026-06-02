"""WARTZ Workflow UI — Linear-style phases viewer.

Сервер:
    python -m wartz_workflow.ui [--port N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

from . import schema, config

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = config.UI_PORT
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="wartz-workflow UI", version="1.2.0")

# ═══════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════


def load_phases() -> list[dict]:
    """Загрузить фазы из YAML с метаданными."""
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
        result = []
        for p in plist:
            grp = next((g for g, ids in _groups.items() if p.id in ids), "other")
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
                    "is_critic": p.is_critic,
                    "gate_label": "БЛОКЕР" if p.is_blocker else ("АГЕНТ" if p.is_delegated else ""),
                    "gate_badge": p.is_blocker or p.is_delegated,
                    "group": grp,
                    "group_name": _group_names.get(grp, "Другое"),
                    "rollback_target": p.rollback_target,
                    "next_recommendation": p.next_recommendation,
                    "parallel_with": p.parallel_with,
                    "skills": p.skills,
                    "delegate_agent": p.delegate.agent if p.delegate else None,
                    "delegate_timeout": p.delegate.timeout_min if p.delegate else None,
                }
            )
        return result
    except Exception:
        return []


def _render_instructions_html(instructions: list, is_delegated: bool) -> str:
    if not instructions:
        return ""
    lines = []
    for idx, i in enumerate(instructions, 1):
        tool = i.get("tool", "")
        tool_html = f'<span style="color:var(--accent)">{tool}</span>' if tool else ""
        sync = "async" if is_delegated else "sync"
        lines.append(
            f'    <div class="instruction">\n'
            f'      <div class="instruction-num">{idx}</div>\n'
            f'      <div class="instruction-text">{i.get("step", "")}</div>\n'
            f'      <div class="instruction-tool">{tool_html}<span class="{sync}">{sync}</span></div>\n'
            f'    </div>'
        )
    return "\n".join(lines)


def _render_checks_html(checks: list) -> str:
    if not checks:
        return ""
    rows = []
    for idx, c in enumerate(checks, 1):
        rows.append(
            f"      <tr><td>{idx}</td><td><code>{c.get('type', '')}</code></td><td>{c.get('description', '')}</td></tr>"
        )
    return "\n".join(rows)


def _render_evidence_html(evidence: list) -> str:
    if not evidence:
        return ""
    rows = []
    for idx, e in enumerate(evidence, 1):
        rows.append(
            f"      <tr><td>{idx}</td><td>{e.get('item', '')}</td><td>{e.get('validator', '—')}</td></tr>"
        )
    return "\n".join(rows)


def load_tasks() -> list[dict]:
    """Задачи из state/*.json (единственный источник правды)."""
    tasks: dict[str, dict] = {}
    state_dir = Path(config.WARTZ_DIR) / "state"
    if state_dir.exists():
        for state_file in state_dir.glob("*.json"):
            jk = state_file.stem
            try:
                with open(state_file, "r") as f:
                    st = json.load(f)
                tasks[jk] = {
                    "task_id": jk,
                    "jira_key": jk,
                    "current_phase": st.get("current_phase", "-"),
                    "phases_completed": st.get("phases_completed", []),
                }
            except Exception:
                pass
    return sorted(tasks.values(), key=lambda x: x["task_id"])


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
h3{font-size:16px;font-weight:600;color:var(--text-secondary);margin:24px 0 12px;letter-spacing:-0.15px}

/* Badges */
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;border:1px solid transparent;white-space:nowrap}
.badge-block{background:rgba(239,68,68,.12);color:#ef4444;border-color:rgba(239,68,68,.25)}
.badge-warn{background:rgba(245,158,11,.12);color:#f59e0b;border-color:rgba(245,158,11,.25)}
.badge-ok{background:rgba(34,197,94,.12);color:#22c55e;border-color:rgba(34,197,94,.25)}
.badge-accent{background:rgba(94,106,210,.12);color:#5e6ad2;border-color:rgba(94,106,210,.25)}

/* Phase list */
.phase-list{display:flex;flex-direction:column;gap:1px;background:var(--border);border-radius:8px;overflow:hidden;border:1px solid var(--border)}
.phase-row{background:var(--surface);padding:14px 18px;display:grid;grid-template-columns:48px 1fr auto;gap:16px;align-items:center;transition:background .1s;cursor:pointer;text-decoration:none;color:inherit}
.phase-row:hover{background:var(--surface-hover)}
.phase-num{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:500;color:var(--text-dim);text-align:center}
.phase-name{font-size:14px;font-weight:500;color:var(--text);letter-spacing:-0.12px}
.phase-desc{font-size:12px;color:var(--text-muted);margin-top:2px;letter-spacing:-0.1px}
.phase-badges{display:flex;gap:6px;align-items:center}
.phase-group-title{font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;margin:28px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--border)}

/* Phase detail */
.phase-detail-header{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px 24px;margin-bottom:16px}
.phase-detail-header h2{margin:0;font-size:20px;font-weight:500;letter-spacing:-0.25px}
.phase-detail-header .meta{display:flex;gap:12px;margin-top:8px;flex-wrap:wrap}
.phase-detail-header .meta span{color:var(--text-muted);font-size:12px}
.phase-detail-header .meta span b{color:var(--text-secondary);font-weight:500}

.detail-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 20px;margin-bottom:12px}
.detail-card h3{margin:0 0 12px;font-size:14px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.06em}
.detail-card.empty{color:var(--text-dim);font-size:13px}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 12px;font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;border-bottom:1px solid var(--border-strong);background:var(--panel)}
td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text-secondary);vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}

/* Code */
code{background:rgba(255,255,255,.04);padding:2px 6px;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-secondary);border:1px solid var(--border)}
pre{background:rgba(255,255,255,.02);padding:12px;border-radius:6px;overflow:auto;font-family:'JetBrains Mono',monospace;font-size:12px;border:1px solid var(--border);color:var(--text-muted)}

/* Instructions */
.instruction{display:grid;grid-template-columns:28px 1fr auto;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);align-items:start}
.instruction:last-child{border-bottom:none}
.instruction-num{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-dim);padding-top:2px}
.instruction-text{font-size:13px;color:var(--text-secondary);line-height:1.5}
.instruction-tool{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;white-space:nowrap;text-align:right}
.instruction-tool .sync{color:var(--text-muted)}
.instruction-tool .async{color:var(--accent)}

/* Back link */
.back-link{display:inline-flex;align-items:center;gap:6px;color:var(--text-muted);text-decoration:none;font-size:13px;font-weight:500;margin-bottom:16px;transition:color .15s}
.back-link:hover{color:var(--text)}

/* Footer */
footer{margin-top:40px;padding:16px 0;border-top:1px solid var(--border);color:var(--text-dim);font-size:12px;text-align:center}
</style>
"""

HEADER_HTML = """
<header>
  <h1>wartz<span style="color:var(--accent)">workflow</span></h1>
  <nav>
    <a href="/phases">Фазы</a>
    <a href="/tasks">Задачи</a>
  </nav>
</header>
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WARTZ Workflow</title>{{ style | safe }}</head>
<body>{{ header | safe }}
<div class="container">
  <div style="margin:40px 0">
    <h2 style="font-size:32px;letter-spacing:-0.7px;margin-bottom:16px">Workflow CLI</h2>
    <p style="color:var(--text-muted);font-size:16px;max-width:600px;line-height:1.6">Декларативный workflow для агентов. Каждая фаза определена в YAML — единый источник истины.</p>
  </div>
  <div class="detail-card">
    <h3>Команды</h3>
    <div class="instruction" style="border-bottom:none">
      <div class="instruction-num">1</div>
      <div class="instruction-text"><code>hrflow workflow TASK-123 "отчёт..."</code> — отправить отчёт по выполненной фазе</div>
      <div class="instruction-tool"><span class="sync">sync</span></div>
    </div>
    <div class="instruction" style="border-bottom:none">
      <div class="instruction-num">2</div>
      <div class="instruction-text"><code>hrflow done-list TASK-123</code> — показать пройденные этапы</div>
      <div class="instruction-tool"><span class="sync">sync</span></div>
    </div>
  </div>
  <div class="detail-card">
    <h3>Быстрые ссылки</h3>
    <p style="margin-top:8px"><a href="/phases" style="color:var(--accent);text-decoration:none;font-size:14px">→ Все фазы workflow</a></p>
    <p><a href="/tasks" style="color:var(--accent);text-decoration:none;font-size:14px">→ Активные задачи</a></p>
  </div>
</div>
<footer>wartz-workflow UI v1.2.0</footer>
</body></html>"""

PHASES_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Фазы — wartz-workflow</title>{{ style | safe }}</head>
<body>{{ header | safe }}
<div class="container">
  <h2>Все фазы workflow ({{ phases|length }})</h2>
  <div class="phase-list">
    {% for p in phases %}
    <a class="phase-row" href="/phase/{{ p.id }}">
      <div class="phase-num">{{ p.phase_num }}</div>
      <div>
        <div class="phase-name">{{ p.name }}</div>
        {% if p.description %}<div class="phase-desc">{{ p.description }}</div>{% endif %}
      </div>
      <div class="phase-badges">
        {% if p.gate_label %}<span class="badge {{ p.is_blocker and 'badge-block' or 'badge-warn' }}">{{ p.gate_label }}</span>{% endif %}
      </div>
    </a>
    {% endfor %}
  </div>
</div>
<footer>wartz-workflow UI v1.2.0</footer>
</body></html>"""

PHASE_DETAIL_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Фаза {{ phase.phase_num }} — {{ phase.name }}</title>{{ style | safe }}</head>
<body>{{ header | safe }}
<div class="container">
  <a href="/phases" class="back-link">← Все фазы</a>

  <div class="phase-detail-header">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
      <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-dim)">№{{ phase.phase_num }}</span>
      <h2>{{ phase.name }}</h2>
      {% if phase.gate_label %}<span class="badge {{ phase.is_blocker and 'badge-block' or 'badge-warn' }}">{{ phase.gate_label }}</span>{% endif %}
    </div>
    {% if phase.description %}<p style="color:var(--text-muted);font-size:14px;margin-top:4px">{{ phase.description }}</p>{% endif %}
    <div class="meta">
      {% if phase.skills %}<span><b>Skills:</b> {{ phase.skills|join(', ') }}</span>{% endif %}
      {% if phase.delegate_agent %}<span><b>Агент:</b> {{ phase.delegate_agent }} ({{ phase.delegate_timeout }}мин)</span>{% endif %}
      {% if phase.parallel_with %}<span><b>Параллельно с:</b> {{ phase.parallel_with }}</span>{% endif %}
      {% if phase.rollback_target %}<span><b>Откат:</b> {{ phase.rollback_target }}</span>{% endif %}
      {% if phase.next_recommendation %}<span><b>Следующая:</b> {{ phase.next_recommendation }}</span>{% endif %}
    </div>
  </div>

  {% if instructions_html %}
  <div class="detail-card">
    <h3>Инструкции ({{ instructions_count }})</h3>
    {{ instructions_html | safe }}
  </div>
  {% endif %}

  {% if checks_html %}
  <div class="detail-card">
    <h3>Проверки / Чекапы ({{ checks_count }})</h3>
    <table>
      <tr><th>#</th><th>Тип</th><th>Описание</th></tr>
      {{ checks_html | safe }}
    </table>
  </div>
  {% else %}
  <div class="detail-card empty">Нет проверок для этой фазы.</div>
  {% endif %}

  {% if evidence_html %}
  <div class="detail-card">
    <h3>Evidence ({{ evidence_count }})</h3>
    <table>
      <tr><th>#</th><th>Что собрать</th><th>Валидатор</th></tr>
      {{ evidence_html | safe }}
    </table>
  </div>
  {% else %}
  <div class="detail-card empty">Нет требований к evidence.</div>
  {% endif %}

</div>
<footer>wartz-workflow UI v1.2.0</footer>
</body></html>"""

TASKS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Задачи — wartz-workflow</title>{{ style | safe }}</head>
<body>{{ header | safe }}
<div class="container">
  <h2>Активные задачи ({{ tasks|length }})</h2>
  {% if tasks %}
  <div class="phase-list">
    {% for t in tasks %}
    <div class="phase-row" style="cursor:default">
      <div class="phase-num" style="font-family:'JetBrains Mono',monospace">{{ t.jira_key }}</div>
      <div>
        <div class="phase-name">Текущая фаза: {{ t.current_phase }}</div>
        <div class="phase-desc">Пройдено фаз: {{ t.phases_completed|length }}</div>
      </div>
      <div class="phase-badges"><span class="badge badge-ok">active</span></div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="detail-card empty">Нет активных задач. Используйте <code>hrflow workflow TASK-KEY</code> чтобы начать.</div>
  {% endif %}
</div>
<footer>wartz-workflow UI v1.2.0</footer>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════
#  RENDERER
# ═══════════════════════════════════════════════════════════════════════


class InlineTemplates:
    """Fallback рендер inline HTML."""

    def __init__(self):
        self.cache = {}

    def TemplateResponse(self, name: str, context: dict):
        from starlette.responses import HTMLResponse
        html_map = {
            "index.html": INDEX_HTML,
            "phases.html": PHASES_HTML,
            "phase_detail.html": PHASE_DETAIL_HTML,
            "tasks.html": TASKS_HTML,
        }
        tmpl = html_map.get(name, f"<!-- Template {name} not found -->")
        rendered = tmpl.replace("{{ style | safe }}", PAGE_STYLE)
        rendered = rendered.replace("{{ header | safe }}", HEADER_HTML)

        if "{% for" in rendered:
            return HTMLResponse(self._render_jinja_like(rendered, context))
        rendered = self._substitute_vars(rendered, context)
        return HTMLResponse(rendered)

    def _substitute_vars(self, template: str, context: dict) -> str:
        result = template
        for match in re.finditer(r"\{\{\s*([^}]+)\s*\}\}", result):
            expr = match.group(1).strip()
            val = self._resolve_expr(expr, context)
            result = result.replace(match.group(0), str(val))
        return result

    def _resolve_expr(self, expr: str, context: dict) -> str:
        if " or " in expr:
            parts = expr.split(" or ", 1)
            left = self._resolve_expr(parts[0].strip(), context)
            if left:
                return left
            right_raw = parts[1].strip()
            if (right_raw.startswith("'") and right_raw.endswith("'")) or (right_raw.startswith('"') and right_raw.endswith('"')):
                return right_raw[1:-1]
            return self._resolve_expr(right_raw, context)

        if "|" in expr:
            parts = expr.split("|", 1)
            base_expr = parts[0].strip()
            filter_expr = parts[1].strip()
            val = self._resolve_expr(base_expr, context)
            if "length" in filter_expr:
                try:
                    return str(len(val) if val else 0)
                except Exception:
                    return "0"
            if "join" in filter_expr:
                try:
                    sep = ", "
                    return sep.join(str(v) for v in val)
                except Exception:
                    return str(val)
            return str(val)

        if "." in expr and not expr.startswith("'"):
            parts = expr.split(".")
            obj = context.get(parts[0], "")
            for attr in parts[1:]:
                if isinstance(obj, dict):
                    obj = obj.get(attr, "")
                elif hasattr(obj, attr):
                    obj = getattr(obj, attr, "")
                else:
                    obj = ""
            return str(obj) if obj is not None else ""

        val = context.get(expr, "")
        return str(val) if val is not None else ""

    def _render_jinja_like(self, template: str, context: dict) -> str:
        lines = template.split("\n")
        output = []
        i = 0
        stack = []

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("{% if "):
                cond = stripped[6:-2].strip()
                parts = cond.split(" ", 2)
                var_name = parts[0]
                if var_name.startswith("phase."):
                    var_name = var_name[6:]
                    val = context.get("phase", {}).get(var_name, "")
                elif var_name.startswith("item."):
                    var_name = var_name[5:]
                    val = context.get("item", {}).get(var_name, "")
                elif "." in var_name:
                    parts2 = var_name.split(".")
                    val = context.get(parts2[0], {})
                    for p in parts2[1:]:
                        val = val.get(p, "") if isinstance(val, dict) else ""
                else:
                    val = context.get(var_name, "")

                op = parts[1] if len(parts) > 1 else ""
                target = parts[2].strip("'\"") if len(parts) > 2 else ""
                if op == "==":
                    cond_result = str(val) == target
                elif op == "!=":
                    cond_result = str(val) != target
                elif op == "and":
                    # simple and support
                    cond_result = bool(val)
                else:
                    cond_result = bool(val)

                stack.append(("if", cond_result, i))
                if not cond_result:
                    depth = 1
                    j = i + 1
                    while j < len(lines) and depth > 0:
                        s = lines[j].strip()
                        if s.startswith("{% if "):
                            depth += 1
                        elif s == "{% endif %}":
                            depth -= 1
                        elif s.startswith("{% else %}") and depth == 1:
                            stack[-1] = ("if", True, j)
                            i = j
                            break
                        j += 1
                    else:
                        while stack and stack[-1][0] == "if":
                            stack.pop()
                        i = j
                        continue

            elif stripped == "{% else %}":
                if stack and stack[-1][0] == "if" and stack[-1][1]:
                    # Skip to endif
                    depth = 1
                    j = i + 1
                    while j < len(lines) and depth > 0:
                        s = lines[j].strip()
                        if s.startswith("{% if "):
                            depth += 1
                        elif s == "{% endif %}":
                            depth -= 1
                        j += 1
                    i = j - 1
                else:
                    stack[-1] = ("if", True, i)

            elif stripped == "{% endif %}":
                if stack and stack[-1][0] == "if":
                    stack.pop()

            elif stripped.startswith("{% for "):
                loop_expr = stripped[6:-2].strip()
                var_name, collection = loop_expr.split(" in ", 1)
                var_name = var_name.strip()
                collection = collection.strip()
                items = self._resolve_expr(collection, context)
                if not isinstance(items, list):
                    items = list(items) if items else []
                loop_body_start = i + 1
                depth = 1
                j = loop_body_start
                while j < len(lines) and depth > 0:
                    s = lines[j].strip()
                    if s.startswith("{% for "):
                        depth += 1
                    elif s == "{% endfor %}":
                        depth -= 1
                    j += 1
                loop_body_end = j - 1
                loop_body = "\n".join(lines[loop_body_start:loop_body_end])
                for idx, item in enumerate(items):
                    item_context = dict(context)
                    item_context[var_name] = item
                    item_context["loop"] = {"index": idx + 1}
                    rendered_item = self._render_jinja_like(loop_body, item_context)
                    output.append(rendered_item)
                i = j - 1

            elif stripped == "{% endfor %}":
                pass

            else:
                output.append(line)

            i += 1

        result = "\n".join(output)
        result = self._substitute_vars(result, context)
        return result


templates = InlineTemplates()


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/phases", response_class=HTMLResponse)
def phases_page(request: Request):
    phases = load_phases()
    return templates.TemplateResponse(
        "phases.html",
        {"request": request, "phases": phases},
    )


@app.get("/phase/{phase_id}", response_class=HTMLResponse)
def phase_detail(request: Request, phase_id: str):
    phases = load_phases()
    phase = next((p for p in phases if p["id"] == phase_id), None)
    if not phase:
        return HTMLResponse("<h1>Phase not found</h1>", status_code=404)
    return templates.TemplateResponse(
        "phase_detail.html",
        {
            "request": request,
            "phase": phase,
            "instructions_html": _render_instructions_html(
                phase.get("instructions", []), phase.get("is_delegated", False)
            ),
            "checks_html": _render_checks_html(phase.get("checks", [])),
            "evidence_html": _render_evidence_html(phase.get("evidence", [])),
        },
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    tasks = load_tasks()
    return templates.TemplateResponse(
        "tasks.html",
        {"request": request, "tasks": tasks},
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
    ensure_templates()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def ensure_templates():
    """Создать templates/ с inline шаблонами."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "index.html": INDEX_HTML,
        "phases.html": PHASES_HTML,
        "phase_detail.html": PHASE_DETAIL_HTML,
        "tasks.html": TASKS_HTML,
    }
    for name, content in files.items():
        path = TEMPLATES_DIR / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
