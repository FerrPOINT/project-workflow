from __future__ import annotations

from project_workflow.interfaces.ui.templates import env
from tests.test_ui_shell_template import Elements


def test_task_detail_renders_group_markers_and_chronological_supervisor_dialog() -> None:
    template = env.get_template("task_detail.html")
    blocks = [
        {
            "kind": "single",
            "status": "done",
            "phases": [
                {"phase_code": "0", "phase_name": "Start", "sequence_number": 1, "status": "done"}
            ],
        },
        {
            "kind": "parallel",
            "status": "done",
            "phases": [
                {"phase_code": "0.6", "phase_name": "Research", "sequence_number": 2, "status": "done"},
                {"phase_code": "1", "phase_name": "Analysis", "sequence_number": 3, "status": "done"},
            ],
        },
        {
            "kind": "single",
            "status": "done",
            "phases": [
                {"phase_code": "10", "phase_name": "Auto-Improve", "sequence_number": 27, "status": "done"}
            ],
        },
    ]
    runs = [
        {
            "phase_code": "0",
            "phase_name": "Start",
            "verdict": "pass",
            "verdict_label": "Принято",
            "created_at": "2026-08-21T10:00",
            "worker_report": "first-report",
            "contract": {"message": "Принято", "covered": ["check"], "missing": [], "blockers": []},
            "next_contract": {
                "phase_code": "0.6",
                "phase_name": "Parallel group: 0.6, 1",
                "description": "Два равноправных участника",
                "group_details": [
                    {
                        "phase_code": "0.6",
                        "phase_name": "Research",
                        "instructions": ["Исследуй. Используй навыки: workflow-code-intelligence."],
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
            "verdict_label": "Принято",
            "created_at": "2026-08-21T11:00",
            "worker_report": "second-report",
            "contract": {"message": "Готово", "covered": [], "missing": [], "blockers": []},
            "next_contract": None,
        },
    ]
    html = template.render(
        page="tasks",
        namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
        task={
            "task_key": "RUN-1",
            "title": "RUN-1",
            "namespace_name": "DEFAULT",
            "namespace_cli_command": "workflow-default",
            "created_at": "2026-08-21T09:00",
            "updated_at": "2026-08-21T11:00",
            "status": "done",
            "latest_verdict": "pass",
            "latest_verdict_label": "Принято",
        },
        current_phase_name="Auto-Improve",
        progress_done=27,
        progress_total=27,
        cycles_done=3,
        cycles_total=3,
        phase_history_blocks=blocks,
        step_history=runs,
    )

    phase_markers = [attrs for _, attrs in Elements(html).elements
                     if "base-timeline-marker" in attrs.get("class", "").split()][:3]
    assert [attrs["data-size"] for attrs in phase_markers] == ["small", "large", "small"]
    assert all(attrs["data-tone"] == "success" for attrs in phase_markers)
    assert html.count('class="base-badge phase-sequence"') == 4
    assert '>1</span><strong class="phase-name">Start' in html
    assert '>2</span><strong class="phase-name">Research' in html
    assert '>3</span><strong class="phase-name">Analysis' in html
    assert '>27</span><strong class="phase-name">Auto-Improve' in html
    assert "phase-parallel-inner-arrow" not in html
    assert html.index("first-report") < html.index("second-report")
    assert "Циклы проверки" in html
    assert "История проверок" in html
    assert "Запрос к advisor" in html
    assert "Ответ advisor" in html
    assert "Следующий этап" in html
    assert "Supervisor" not in html

    elements = Elements(html).elements
    disclosures = [attrs for tag, attrs in elements if tag == "details" and
                   "base-disclosure" in attrs.get("class", "").split()]
    assert len(disclosures) == 2
    assert ["open" in attrs for attrs in disclosures] == [False, True]
    assert all(attrs["data-appearance"] == "row" for attrs in disclosures)
    summaries = [attrs for tag, attrs in elements if tag == "summary" and
                 "base-resource-list-row" in attrs.get("class", "").split()]
    assert len(summaries) == 2
    links = [attrs["href"] for tag, attrs in elements if tag == "a" and
             "base-section-navigation-item" in attrs.get("class", "").split()]
    assert links == ["#task-summary", "#phase-history-title", "#check-history-title"]
    assert 'class="activity-event-summary"' not in html
    assert "workflow-code-intelligence" in html
    assert "Dataflow проверен" in html
    assert "Лог исследования" in html
    assert "Воркфлоу завершён" in html
    assert "Время в работе" not in html
    assert "СЛЕДУЮЩИЙ ШАГ" not in html
    assert 'data-page-layout="detail-with-aside"' in html
