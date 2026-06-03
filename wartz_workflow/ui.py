"""WARTZ Workflow UI v2 — шаблонный FastAPI + Jinja2 viewer.

Сервер:
    python -m wartz_workflow.ui [--port N] [--host H]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from . import schema, config, db, service

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = config.UI_PORT
BASE_DIR = Path(__file__).parent

# ── Jinja2 templates (v2/ под base.html + extends) ──────────────────────
templates = Jinja2Templates(directory=str(BASE_DIR / "templates" / "v2"))

def _group_instructions(instructions):
    """Группирует инструкции по runs: parallel примыкает к предыдущей sync и идёт с ней рядом."""
    if not instructions:
        return []
    groups = []
    current = [instructions[0]]
    for i in instructions[1:]:
        if i.get('execution_type') == 'parallel':
            current.append(i)          # parallel → в ту же группу (параллельно предыдущей)
        else:
            groups.append(current)      # sync → новый run
            current = [i]
    groups.append(current)
    return groups

templates.env.filters['group_instructions'] = _group_instructions


_db: db.WorkflowDB | None = None
_srv: service.PhaseService | None = None

def _get_db() -> db.WorkflowDB:
    """Singleton + lazy init."""
    global _db
    if _db is None:
        _db = db.WorkflowDB()
        _db.init()
        if _db.is_empty():
            _yaml_to_sqlite()
    return _db

def _get_service() -> service.PhaseService:
    """Service singleton."""
    global _srv
    if _srv is None:
        _srv = service.PhaseService(_get_db())
    return _srv


def _yaml_to_sqlite() -> None:
    """Разовый импорт phases.yaml → SQLite."""
    yaml_phases = schema.load_phases()
    _phase_order = config.PHASE_ORDER
    batch = []
    for p in yaml_phases:
        # Полные данные фазы для шаблона
        extra = {
            "delegate_agent": p.delegate.agent if p.delegate else None,
            "delegate_timeout": p.delegate.timeout_min if p.delegate else None,
            "delegate_max_cycles": p.delegate.max_cycles if p.delegate else None,
            "delegate_toolsets": json.dumps(p.delegate.toolsets) if p.delegate and p.delegate.toolsets else None,
            "parallel_with": p.parallel_with,
            "rollback_target": p.rollback_target,
            "next_recommendation": p.next_recommendation,
            "execution_mode": p.execution_mode if p.execution_mode else ("parallel" if p.is_delegated else "sync"),
        }
        batch.append(
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "phase_order": _phase_order.index(p.id) + 1 if p.id in _phase_order else 0,
                "skills": json.dumps(p.skills) if p.skills else None,
                "instructions": [
                    {
                        "step_num": idx + 1,
                        "description": instr.step,
                        "execution_type": "parallel" if p.is_delegated else "sync",
                        "tool": instr.tool,
                    }
                    for idx, instr in enumerate(p.instructions)
                ],
                "checks": [
                    {"description": c.description, "command": c.command}
                    for c in p.checks
                ],
                "evidence": [
                    {"description": e.item, "validator": e.validator}
                    for e in p.evidence
                ],
                "checkups": [
                    {
                        "name": f"Check {cu}",
                        "check_type": "jira_status",
                        "target": "",
                        "interval_min": 0,
                        "last_status": "unknown",
                        "fail_action": "warn",
                    }
                    for cu in p.checks
                ],
                **extra,
            }
        )
    _db.import_phases(batch)


# Backward-compat alias
_seed_to_sqlite = _yaml_to_sqlite


def _build_execution_batches(phases: list[dict]) -> list[dict]:
    """Разбить фазы на sync/parallel batches для визуализации workflow.

    Синхронные — последовательно, параллельные — объединены в группы по
    parallel_with через connected-components (Union-Find).
    Порядок берётся из DB (phase_order), не из config.PHASE_ORDER.
    """
    if not phases:
        return []

    phases_by_id = {p["id"]: p for p in phases}
    order_map = {p["id"]: p["phase_num"] for p in phases}

    # ── Union-Find для parallel групп ─────────────────────────────────
    parent: dict[str, str] = {p["id"]: p["id"] for p in phases}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            # attach smaller order to larger (arbitrary, deterministic)
            if order_map.get(ra, 0) < order_map.get(rb, 0):
                parent[rb] = ra
            else:
                parent[ra] = rb

    for p in phases:
        target = p.get("parallel_with")
        if target and target in phases_by_id and target != p["id"]:
            _union(p["id"], target)

    # Собрать компоненты
    groups: dict[str, list[str]] = {}
    for pid in phases_by_id:
        root = _find(pid)
        groups.setdefault(root, []).append(pid)

    # Отделить sync от parallel (group size > 1)
    parallel_groups = [
        sorted(g, key=lambda x: order_map.get(x, 0))
        for g in groups.values()
        if len(g) > 1
    ]
    all_parallel_ids = set()
    for g in parallel_groups:
        all_parallel_ids.update(g)

    # ── Сортировка по DB order ────────────────────────────────────────
    sorted_ids = sorted(phases_by_id.keys(), key=lambda x: order_map.get(x, 0))

    batches: list[dict] = []
    used: set[str] = set()

    for pid in sorted_ids:
        if pid in used:
            continue
        if pid in all_parallel_ids:
            # Найти группу и добавить целиком
            for group in parallel_groups:
                if pid in group:
                    batch_phases = [phases_by_id[g] for g in group]
                    batches.append({
                        "type": "parallel",
                        "phases": batch_phases,
                        "title": " + ".join(p["name"] for p in batch_phases),
                    })
                    used.update(group)
                    break
        else:
            batches.append({
                "type": "sync",
                "phases": [phases_by_id[pid]],
                "title": phases_by_id[pid]["name"],
            })
            used.add(pid)

    return batches


def _mermaid_from_batches(batches: list[dict]) -> str:
    """Генерация Mermaid flowchart из batches."""
    lines = ["flowchart TD"]
    nodes = []
    edges = []
    prev_node = None
    
    for batch in batches:
        if len(batch["phases"]) == 1:
            p = batch["phases"][0]
            node = f"{p['id']}".replace(".", "_").replace("-", "neg")
            label = f"P{p['phase_num']}:{p['name'][:20]}"
            nodes.append(f"    {node}[{label}]")
            if prev_node:
                edges.append(f"    {prev_node} --> {node}")
            prev_node = node
        else:
            # Parallel group
            first = batch["phases"][0]
            join_node = f"JOIN_{first['id']}".replace(".", "_").replace("-", "neg")
            parallel_nodes = []
            for p in batch["phases"]:
                node = f"{p['id']}".replace(".", "_").replace("-", "neg")
                label = f"P{p['phase_num']}:{p['name'][:20]}"
                nodes.append(f"    {node}[{label}]")
                parallel_nodes.append(node)
            
            # Join node
            nodes.append(f"    {join_node}{{🔄}}")
            
            if prev_node:
                edges.append(f"    {prev_node} --> {parallel_nodes[0]}")
            for node in parallel_nodes:
                edges.append(f"    {node} --> {join_node}")
            prev_node = join_node
    
    return "\n".join(lines + nodes + edges)


app = FastAPI(title="wartz-workflow UI", version="2.0.0")


# ═══════════════════════════════════════════════════════════════════════
#  PHASE GROUPS (for Kanban)
# ═══════════════════════════════════════════════════════════════════════

PHASE_GROUP_NAMES = {
    "setup": "🔧 Setup",
    "research": "🔬 Research",
    "plan": "📋 Plan",
    "dev": "💻 Dev",
    "qa": "🧪 QA",
    "closure": "🏁 Closure",
}

PHASE_TO_GROUP = {
    "-1": "setup", "0.0a": "setup", "0.01": "setup", "0.01a": "setup", "0.01b": "setup",
    "0": "setup", "0.00": "setup", "0.000": "setup", "0.7": "setup",
    "0.5": "research", "0.6": "research", "0.9": "research", "1": "research", "1.5": "research", "2": "research",
    "3": "plan", "3.5": "plan",
    "4": "dev", "4.5": "dev", "5": "dev", "5.5": "dev",
    "7": "qa", "7.5": "qa", "7.6": "qa", "7.6.R": "qa", "7.7": "qa",
    "6": "closure", "8": "closure", "9": "closure", "10": "closure",
}


def _group_phases(phases: list[dict]) -> dict[str, list[dict]]:
    groups = {k: [] for k in PHASE_GROUP_NAMES}
    for p in phases:
        group = PHASE_TO_GROUP.get(p["id"], "setup")
        # Add instruction count from DB
        wdb = _get_db()
        insts = wdb.get_phase_instructions(p["id"])
        p["instruction_count"] = len(insts)
        groups[group].append(p)
    return groups


# ═══════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════

def _load_phases() -> list[dict]:
    wdb = _get_db()
    rows = wdb.get_phases()
    result = []
    for p in rows:
        skills = json.loads(p["skills"]) if p["skills"] else []
        delegate_agent = p.get("delegate_agent")
        result.append(
            {
                "id": p["id"],
                "phase_num": p["phase_order"],
                "name": p["name"],
                "description": p["description"],
                "skills": skills,
                "delegate_agent": delegate_agent,
                "is_delegated": bool(delegate_agent),
                "parallel_with": p.get("parallel_with"),
                "rollback_target": p.get("rollback_target"),
                "delegate_timeout": p.get("delegate_timeout"),
            }
        )
    return result


def _load_phase_detail(phase_id: str) -> dict | None:
    return _get_service().get_phase_detail(phase_id)


def _load_tasks() -> list[dict]:
    """Загрузить задачи из SQLite."""
    wdb = _get_db()
    tasks = wdb.get_tasks()
    result = []
    
    for t in tasks:
        # Count completed phases
        task_phases = wdb.get_task_phases(t["id"])
        completed = sum(1 for tp in task_phases if tp["status"] == "done")
        
        # Get current phase info
        current_phase_id = t.get("current_phase", "-1")
        phase_map = {p["id"]: p for p in _load_phases()}
        current = phase_map.get(current_phase_id, {})
        
        result.append(
            {
                "id": t["id"],
                "jira_key": t["jira_key"],
                "title": t.get("title", ""),
                "phase_id": current_phase_id,
                "phase_num": current.get("phase_num", "?"),
                "phase_name": current.get("name", current_phase_id),
                "completed": completed,
                "total_phases": len(config.PHASE_ORDER),
                "status": t.get("status", "active"),
                "status_label": "В работе" if t.get("status") != "done" else "Завершена",
                "created_at": t.get("created_at", ""),
            }
        )
    
    return result


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Pages
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    tasks = _load_tasks()
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={
            "request": request,
            "page": "dashboard",
            "ui_port": config.UI_PORT,
            "task_count": len(tasks),
            "completed_phases": sum(t["completed"] for t in tasks),
            "tasks": tasks[:5],
        }
    )


@app.get("/phases", response_class=HTMLResponse)
def phases_page(request: Request):
    phases = _load_phases()
    grouped = _group_phases(phases)
    return templates.TemplateResponse(
        request=request, name="phases.html",
        context={"request": request, "grouped": grouped, "groups": PHASE_GROUP_NAMES, "grouped_phases": grouped, "page": "phases", "ui_port": config.UI_PORT}
    )


@app.get("/execution", response_class=HTMLResponse)
def execution_page(request: Request):
    """Визуальный граф выполнения фаз: sync = последовательно, parallel = ветвления."""
    wdb = _get_db()
    phases = _load_phases()
    # enrich phases with instructions for mini-flow inside each node
    for p in phases:
        p["instructions"] = wdb.get_phase_instructions(p["id"])
    batches = _build_execution_batches(phases)
    mermaid = _mermaid_from_batches(batches)
    return templates.TemplateResponse(
        request=request, name="execution.html",
        context={"request": request, "batches": batches, "mermaid": mermaid, "page": "execution", "ui_port": config.UI_PORT}
    )


@app.get("/phase/{phase_id}", response_class=HTMLResponse)
def phase_detail(request: Request, phase_id: str):
    phase = _load_phase_detail(phase_id)
    if not phase:
        return HTMLResponse("<h1>Phase not found</h1>", status_code=404)
    return templates.TemplateResponse(
        request=request, name="phase_detail.html", context={
            "request": request, "page": "phases", "ui_port": config.UI_PORT, "phase": phase
        }
    )



@app.get("/wizard", response_class=HTMLResponse)
def wizard_page(request: Request):
    phases = _load_phases()
    return templates.TemplateResponse(
        request=request, name="wizard_list.html", context={
            "request": request, "page": "wizard", "ui_port": config.UI_PORT, "phases": phases,
        }
    )


@app.get("/wizard/{phase_id}", response_class=HTMLResponse)
def wizard_phase_page(request: Request, phase_id: str):
    """Wizard для конкретной фазы — вопросы из phases.yaml + чеклист + evidence."""
    wdb = _get_db()
    
    # Get phase from DB
    phase_row = wdb.get_phase(phase_id)
    if not phase_row:
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    
    phase = dict(phase_row)
    phase["phase_num"] = config.PHASE_ORDER.index(phase_id) + 1 if phase_id in config.PHASE_ORDER else 0
    phase["is_blocker"] = bool(phase.get("is_blocker"))
    phase["is_delegated"] = bool(phase.get("delegate_agent"))
    
    # Load questions from DB only
    questions = wdb.get_questions(phase_id)

    # Load checklist from instructions + checks
    instructions = wdb.get_instructions(phase_id)
    checks = wdb.get_checks(phase_id)
    checklist = []
    for inst in instructions:
        checklist.append({"text": inst["description"], "checked": False, "type": "instruction"})
    for c in checks:
        checklist.append({"text": c["description"], "checked": False, "type": "check"})
    
    # Load evidence
    evidence = wdb.get_evidence(phase_id)
    
    # Load saved answers (if any)
    answers = {}  # qid -> answer_text
    
    return templates.TemplateResponse(
        request=request, name="wizard.html",
        context={
            "request": request,
            "page": "wizard",
            "ui_port": config.UI_PORT,
            "phase": phase,
            "questions": questions,
            "checklist": checklist,
            "evidence": evidence,
            "answers": answers,
        }
    )


@app.post("/api/wizard/{phase_id}")
def api_wizard_submit(phase_id: str, body: dict[str, Any]):
    """Проверка ответов wizard: возвращает PASS/FAIL."""
    wdb = _get_db()
    
    # Load phase questions from DB only
    questions = wdb.get_questions(phase_id)

    # Get answers from body
    user_answers = body.get("answers", {})
    checks = body.get("checks", {})
    
    covered = []
    missing = []
    
    # Check questions
    for q in questions:
        qid = f"q_{q['id']}"
        answer = user_answers.get(qid, "").strip()
        
        if q.get("required") and not answer:
            missing.append(q["qtext"])
            continue
        
        # Check keywords
        keywords = json.loads(q.get("expected_keywords", "[]")) if q.get("expected_keywords") else []
        if keywords and answer:
            ans_lower = answer.lower()
            matched = any(k.lower() in ans_lower for k in keywords)
            if not matched and q.get("required"):
                missing.append(f"{q['qtext']} (keywords: {', '.join(keywords)})")
            elif matched:
                covered.append(q["qtext"])
        elif answer:
            covered.append(q["qtext"])
    
    # Check checklist items
    checklist_items = body.get("checklist", {})
    for key, checked in checklist_items.items():
        if not checked:
            missing.append(f"Чеклист: пункт {key}")
    
    # Evaluate verdict
    if not missing:
        from . import phases as phases_mod
        next_phase = phases_mod.get_next_phase(phase_id)
        next_phase_row = wdb.get_phase(next_phase) if next_phase else None
        next_name = next_phase_row["name"] if next_phase_row else None

        return {
            "verdict": "PASS",
            "phase": phase_id,
            "covered": covered,
            "missing": [],
            "message": f"Фаза {phase_id} пройдена. Переходим к {next_phase} — {next_name}" if next_phase else "Все фазы выполнены!",
            "next_phase": next_phase,
            "next_phase_name": next_name,
        }
    else:
        return {
            "verdict": "FAIL",
            "phase": phase_id,
            "covered": covered,
            "missing": missing,
            "message": f"Не выполнено {len(missing)} пунктов. Доработай и пришли новый отчёт.",
            "next_phase": None,
            "next_phase_name": None,
        }

@app.get("/api/wizard/{jira_key}/context")
def api_wizard_context(jira_key: str):
    """Полный контекст для агента-визарда."""
    from . import wizard as wizard_mod
    engine = wizard_mod.WizardEngine(jira_key)
    return engine.get_full_context()


# ── Settings ─────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Страница настроек workflow."""
    s = config.load_settings()
    if "key_patterns" not in s:
        s["key_patterns"] = config.DEFAULT_SETTINGS.get("key_patterns", [
            r"^TASKNEIROKLYUCH-(?P<number>[0-9]+)$",
            r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)$",
        ])
    return templates.TemplateResponse(
        request=request, name="settings.html", context={
            "request": request,
            "settings": s,
        },
    )


@app.get("/api/settings")
def api_settings_get():
    """Вернуть текущие настройки."""
    return {"ok": True, "settings": config.load_settings()}


@app.put("/api/settings")
def api_settings_put(body: dict[str, Any]):
    """Сохранить настройки."""
    config.save_settings(body)
    return {"ok": True}


@app.delete("/api/settings")
def api_settings_delete():
    """Сбросить настройки к defaults."""
    import json, os
    settings_path = os.path.expanduser("~/.wartz-workflow/settings.json")
    if os.path.exists(settings_path):
        os.remove(settings_path)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/phases")
def api_phases():
    return {"ok": True, "phases": _load_phases()}


@app.get("/api/phases/{phase_id}")
def api_phase_detail(phase_id: str):
    phase = _load_phase_detail(phase_id)
    if not phase:
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    return {"ok": True, "phase": phase}


@app.get("/api/groups")
def api_groups():
    """Получить все группы фаз."""
    wdb = _get_db()
    wdb.seed_default_groups()
    groups = wdb.get_phase_groups()
    return {"ok": True, "groups": groups}


@app.post("/api/groups")
def api_group_create(body: dict[str, Any]):
    """Создать группу фаз."""
    group_id = body.get("id", "").strip().lower()
    name = body.get("name", "").strip()
    if not group_id or not name:
        return JSONResponse({"ok": False, "error": "id and name required"}, status_code=400)
    wdb = _get_db()
    existing = wdb.get_phase_group(group_id)
    if existing:
        return JSONResponse({"ok": False, "error": f"Group {group_id} already exists"}, status_code=409)
    wdb.create_phase_group({
        "id": group_id, "name": name, "icon": body.get("icon"),
        "sort_order": body.get("sort_order", 0),
    })
    return {"ok": True, "group_id": group_id}


@app.put("/api/groups/order")
def api_groups_order(body: dict[str, Any]):
    """Обновить порядок групп (DND колонок)."""
    orders = body.get("orders", [])
    if not orders:
        return JSONResponse({"ok": False, "error": "No orders provided"}, status_code=400)
    wdb = _get_db()
    batch = [(o["group_id"], o["sort_order"]) for o in orders]
    wdb.batch_update_group_orders(batch)
    return {"ok": True, "updated": len(batch)}


@app.put("/api/groups/{group_id}")
def api_group_update(group_id: str, body: dict[str, Any]):
    """Обновить группу."""
    wdb = _get_db()
    existing = wdb.get_phase_group(group_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Group not found"}, status_code=404)
    update_data = {}
    if "name" in body: update_data["name"] = body["name"]
    if "icon" in body: update_data["icon"] = body["icon"]
    if "sort_order" in body: update_data["sort_order"] = body["sort_order"]
    if update_data:
        wdb.update_phase_group(group_id, update_data)
    return {"ok": True}


@app.delete("/api/groups/{group_id}")
def api_group_delete(group_id: str):
    """Удалить группу. Фазы переходят в setup."""
    wdb = _get_db()
    existing = wdb.get_phase_group(group_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Group not found"}, status_code=404)
    wdb.delete_phase_group(group_id)
    return {"ok": True}


@app.put("/api/phases/{phase_id}/group")
def api_phase_group_assign(phase_id: str, body: dict[str, Any]):
    """Назначить фазу в группу."""
    group_id = body.get("group_id")
    if not group_id:
        return JSONResponse({"ok": False, "error": "group_id required"}, status_code=400)
    wdb = _get_db()
    if not wdb.get_phase(phase_id):
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    if not wdb.get_phase_group(group_id):
        return JSONResponse({"ok": False, "error": "Group not found"}, status_code=404)
    wdb.update_phase_group_assignment(phase_id, group_id)
    return {"ok": True}


@app.put("/api/phases/order")
def api_update_order(body: dict[str, Any]):
    """Batch update phase_order после drag-and-drop на Kanban.

    Body: {"orders": [{"phase_id": "4", "phase_order": 8}, ...]}
    """
    orders = body.get("orders", [])
    if not orders:
        return JSONResponse({"ok": False, "error": "No orders provided"}, status_code=400)

    wdb = _get_db()
    batch = [(o["phase_id"], o["phase_order"]) for o in orders]
    wdb.batch_update_orders(batch)

    # Rebuild PHASE_ORDER in config (volatile for this process)
    _update_config_phase_order()

    return {"ok": True, "updated": len(batch)}


@app.put("/api/phases/parallel")
def api_update_parallel(body: dict[str, Any]):
    """Batch update parallel_with связей после drag в графе.

    Body: {"groups": [["4.5", "5"], ["7.5", "7.6"]], "clear": ["3.5"]}
    """
    groups = body.get("groups", [])
    clear = body.get("clear", [])

    wdb = _get_db()

    # Collect ALL phase IDs that will be in new groups → must have old links wiped
    all_group_ids = set()
    for group in groups:
        if len(group) >= 2:
            all_group_ids.update(group)

    # Clear old parallel links for anyone entering a new group or explicitly cleared
    to_clear = all_group_ids | set(clear)
    for phase_id in to_clear:
        wdb.update_phase_parallel(phase_id, None)

    # Set new bidirectional links (cycle for groups >=2)
    group_map: dict[str, str] = {}
    for group in groups:
        if len(group) >= 2:
            for i, phase_id in enumerate(group):
                target = group[(i + 1) % len(group)]
                group_map[phase_id] = target

    if group_map:
        wdb.batch_update_groups(group_map)

    return {"ok": True, "groups_set": len(group_map), "cleared": len(to_clear)}


@app.put("/api/phases/{phase_id}")
def api_phase_update(phase_id: str, body: dict[str, Any]):
    srv = _get_service()
    if not srv.get_phase_detail(phase_id):
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)

    # Phase metadata
    PHASE_FIELDS = {
        "name", "description", "skills", "delegate_agent",
        "delegate_timeout", "delegate_max_cycles", "delegate_toolsets",
        "parallel_with", "rollback_target", "next_recommendation",
    }
    phase_data = {k: v for k, v in body.items() if k in PHASE_FIELDS}
    if phase_data:
        srv.update_phase(phase_id, phase_data)

    # Bulk replace instructions / checks / evidence
    inst_ids = srv.save_instructions(phase_id, body.get("instructions", []))
    check_ids = srv.save_checks(phase_id, body.get("checks", []))
    ev_ids = srv.save_evidence(phase_id, body.get("evidence", []))

    return {"ok": True, "ids": {"instructions": inst_ids, "checks": check_ids, "evidence": ev_ids}}


@app.delete("/api/instructions/{inst_id}")
def api_delete_instruction(inst_id: int):
    wdb = _get_db()
    wdb.delete_instruction(inst_id)
    return {"ok": True}


@app.delete("/api/checks/{check_id}")
def api_delete_check(check_id: int):
    wdb = _get_db()
    wdb.delete_check(check_id)
    return {"ok": True}


@app.delete("/api/evidence/{ev_id}")
def api_delete_evidence(ev_id: int):
    wdb = _get_db()
    wdb.delete_evidence(ev_id)
    return {"ok": True}


@app.put("/api/phases/{phase_id}/order")
def api_single_phase_order(phase_id: str, body: dict[str, Any]):
    """Обновить порядок одной фазы (перетаскивание в графе)."""
    new_order = body.get("phase_order")
    if new_order is None:
        return JSONResponse({"ok": False, "error": "phase_order required"}, status_code=400)

    wdb = _get_db()
    wdb.update_phase_order(phase_id, int(new_order))

    # Rebuild config order
    _update_config_phase_order()

    return {"ok": True, "phase_id": phase_id, "phase_order": new_order}


def _update_config_phase_order():
    """Пересобрать PHASE_ORDER из актуального DB state."""
    phases = _load_phases()
    sorted_phases = sorted(phases, key=lambda p: p["phase_num"])
    config.PHASE_ORDER[:] = [p["id"] for p in sorted_phases]


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="WARTZ Workflow UI v2")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: %(default)s)")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
