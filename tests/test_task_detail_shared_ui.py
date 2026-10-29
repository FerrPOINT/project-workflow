from __future__ import annotations

from html.parser import HTMLParser

import pytest

from project_workflow.interfaces.ui.templates import env
from tests.test_ui_shell_template import Elements


def render_detail(**overrides):
    context = {
        "page": "tasks", "can_administer": False,
        "ui_base_path": lambda: "/workflow",
        "namespace_cookie_name": "workflow_namespace_id",
        "namespace_cookie_secure": False,
        "task": {
            "task_key": "OWN-73",
            "title": "Owner <title>",
            "namespace_id": 73,
            "namespace_name": "Owner namespace",
            "namespace_cli_command": "owner-command",
            "workflow_name": "Owner workflow",
            "status": "active",
            "latest_verdict": None,
        },
        "current_phase_name": "Owner phase",
        "progress_done": 2,
        "progress_total": 5,
        "cycles_done": 1,
        "cycles_total": 3,
        "phase_history_blocks": [],
        "step_history": [],
    }
    context.update(overrides)
    return env.get_template("task_detail.html").render(**context)


class Text(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.parts = []
        self.feed(html)

    def handle_data(self, data):
        self.parts.append(data)


@pytest.mark.parametrize("status,label,tone", [
    ("done", "Завершена", "success"),
    ("blocked", "Заблокирована", "danger"),
    ("active", "В работе", "info"),
])
def test_task_status_is_a_shared_badge_with_owner_meaning(status, label, tone):
    html = render_detail(task={"task_key": "T-1", "status": status})
    assert f'class="base-badge" data-tone="{tone}" data-appearance="badge">{label}</span>' in html


@pytest.mark.parametrize("verdict,tone", [
    ("pass", "success"), ("partial", "warning"), ("blocked", "danger"),
    ("rollback", "warning"), ("delegate", "info"), ("future_verdict", "neutral"),
])
def test_verdict_badges_and_result_panels_preserve_labels_reports_and_lists(verdict, tone):
    task = {"task_key": "T-1", "status": "active", "latest_verdict": verdict,
            "latest_verdict_label": "Owner <verdict>"}
    html = render_detail(task=task, step_history=[{
        "phase_code": "P-73", "phase_name": "Owner phase", "verdict": verdict,
        "verdict_label": "Owner <verdict>", "created_at": "2026-10-23T12:34",
        "worker_report": "First line\n<script>owner report</script>",
        "contract": {"message": "Owner <result>", "covered": ["Covered <safe>"],
                     "missing": ["Missing <safe>"], "blockers": ["Blocker <safe>"]},
        "next_contract": None,
    }])
    assert html.count(f'data-tone="{tone}" data-appearance="badge">Owner &lt;verdict&gt;') == 2
    result = next(attrs for _, attrs in Elements(html).elements
                  if attrs.get("id") == "check-result-1")
    assert "base-notice" in result["class"].split()
    assert result["data-tone"] == tone
    assert "role" not in result  # Historical results are not repeated live alerts.
    for text in ["Owner &lt;result&gt;", "Covered &lt;safe&gt;", "Missing &lt;safe&gt;", "Blocker &lt;safe&gt;",
                 "First line\n&lt;script&gt;owner report&lt;/script&gt;"]:
        assert text in html
    assert 'data-preserve-line-breaks="true"' in html
    markers = [attrs for _, attrs in Elements(html).elements
               if "base-timeline-marker" in attrs.get("class", "").split()]
    assert len(markers) == 1
    assert markers[0]["data-tone"] == tone
    assert markers[0]["aria-hidden"] == "true"
    assert "data-current" not in markers[0]



@pytest.mark.parametrize("done,total,current,variant", [
    (0, 0, None, "default"), (0, 5, "0", "default"), (2, 5, "2", "default"),
    (5, 5, "5", "success"), (7, 5, "5", "success"), (-2, 5, "0", "default"),
])
def test_shared_progress_has_accessible_units_without_changing_owner_counts(done, total, current, variant):
    html = render_detail(progress_done=done, progress_total=total)
    bars = [attrs for _, attrs in Elements(html).elements if attrs.get("role") == "progressbar"]
    assert len(bars) == 2
    phase = next(attrs for attrs in bars if attrs["aria-label"] == "Фазы воркфлоу")
    assert phase.get("aria-valuenow") == current
    assert phase.get("aria-valuemax") == (str(total) if total else None)
    assert phase.get("data-unknown") == ("true" if not total else None)
    assert phase["data-variant"] == variant
    assert phase["aria-valuetext"] == f"{done} / {total}"
    assert f"{done} / {total}" in "".join(Text(html).parts)
    cycles = next(attrs for attrs in bars if attrs["aria-label"] == "Циклы проверки")
    assert cycles["aria-valuenow"] == "1"
    assert cycles["aria-valuemax"] == "3"


def test_shared_header_has_one_back_action_and_keeps_namespace_title_and_native_navigation():
    html = render_detail()
    elements = Elements(html).elements
    back = [attrs for tag, attrs in elements if tag == "a" and
            attrs.get("href") == "/workflow/tasks?profession_id=73"]
    assert len(back) == 1
    assert "base-button" in back[0]["class"].split()
    assert "onclick" not in back[0]
    headings = [attrs for tag, attrs in elements if tag == "h1"]
    assert len(headings) == 1
    assert "base-page-title" in headings[0]["class"].split()
    assert "Owner &lt;title&gt;" in html
    assert "Owner workflow" in html
    assert "owner-command" in html
    states = [attrs.get("data-page-state") for _, attrs in elements if "data-page-state" in attrs]
    assert states.count("empty") == 2


@pytest.mark.parametrize("status,label,tone,highlighted", [
    ("done", "Завершена", "success", False),
    ("current", "Текущая", "info", True),
    ("pending", "Ожидает", "muted", False),
])
def test_phase_surfaces_use_base_and_keep_phase_sequence_and_status(status, label, tone, highlighted):
    html = render_detail(phase_history_blocks=[{
        "kind": "single", "status": status,
        "phases": [{"sequence_number": 73, "phase_code": "P-73", "phase_name": "Owner <phase>",
                    "phase_description": "Owner <description>", "status": status}],
    }])
    markers = [attrs for _, attrs in Elements(html).elements
               if "base-timeline-marker" in attrs.get("class", "").split()]
    assert len(markers) == 1
    assert markers[0]["data-tone"] == {"done": "success", "current": "info"}.get(status, "neutral")
    assert markers[0]["data-size"] == "small"
    assert (markers[0].get("data-current") == "true") is highlighted
    assert markers[0]["aria-hidden"] == "true"
    assert f'data-tone="{tone}" data-appearance="badge">{label}</span>' in html
    assert 'data-appearance="counter"><span class="phase-sequence-label base-visually-hidden">Фаза </span>73' in html
    assert "Owner &lt;phase&gt;" in html
    assert "Owner &lt;description&gt;" in html
    highlighted_cards = [attrs for _, attrs in Elements(html).elements
                         if "base-card" in attrs.get("class", "").split()
                         and attrs.get("data-highlighted") == "true"]
    assert len(highlighted_cards) == int(highlighted)
