from __future__ import annotations

from project_workflow.interfaces.ui.templates import env


def test_task_detail_renders_group_markers_and_chronological_wizard_dialog() -> None:
    template = env.get_template("task_detail.html")
    blocks = [
        {
            "kind": "single",
            "status": "done",
            "phases": [{"phase_code": "0", "phase_name": "Start", "status": "done"}],
        },
        {
            "kind": "parallel",
            "status": "done",
            "phases": [
                {"phase_code": "0.6", "phase_name": "Research", "status": "done"},
                {"phase_code": "1", "phase_name": "Analysis", "status": "done"},
            ],
        },
        {
            "kind": "single",
            "status": "done",
            "phases": [{"phase_code": "10", "phase_name": "Auto-Improve", "status": "done"}],
        },
    ]
    runs = [
        {
            "phase_code": "0",
            "phase_name": "Start",
            "verdict": "pass",
            "verdict_label": "PASS",
            "created_at": "2026-08-21T10:00",
            "report": "first-report",
            "contract": {"message": "Принято", "covered": ["check"], "missing": [], "blockers": []},
            "next_contract": {
                "phase_code": "0.6",
                "phase_name": "Parallel group: 0.6, 1",
                "description": "Два равноправных участника",
                "group_details": [
                    {
                        "phase_code": "0.6",
                        "phase_name": "Research",
                        "instructions": ["Исследуй. Используй skills: workflow-code-intelligence."],
                        "required_checks": ["Dataflow проверен"],
                        "required_evidence": ["Лог исследования"],
                    },
                    {
                        "phase_code": "1",
                        "phase_name": "Analysis",
                        "instructions": ["Собери требования"],
                        "required_checks": ["Требования согласованы"],
                        "required_evidence": ["Документ требований"],
                    },
                ],
            },
        },
        {
            "phase_code": "10",
            "phase_name": "Auto-Improve",
            "verdict": "pass",
            "verdict_label": "PASS",
            "created_at": "2026-08-21T11:00",
            "report": "second-report",
            "contract": {"message": "Готово", "covered": [], "missing": [], "blockers": []},
            "next_contract": None,
        },
    ]
    html = template.render(
        page="tasks",
        task={
            "task_key": "TASK-1",
            "title": "TASK-1",
            "project_label": "DEFAULT",
            "created_at": "2026-08-21T09:00",
            "updated_at": "2026-08-21T11:00",
            "status": "done",
            "latest_verdict": "pass",
            "latest_verdict_label": "PASS",
        },
        current_phase_name="Auto-Improve",
        progress_done=27,
        progress_total=27,
        work_time="2 ч",
        phase_history_blocks=blocks,
        supervisor_runs=runs,
    )

    assert html.count('class="phase-node serial done"') == 2
    assert html.count('class="phase-node parallel done"') == 1
    assert "phase-parallel-inner-arrow" not in html
    assert html.index("first-report") < html.index("second-report")
    assert "Диалог с Wizard" in html
    assert "Задание Wizard на следующий этап" in html
    assert "workflow-code-intelligence" in html
    assert "Dataflow проверен" in html
    assert "Лог исследования" in html
    assert "Workflow завершён" in html
    assert "СЛЕДУЮЩИЙ ШАГ" not in html

