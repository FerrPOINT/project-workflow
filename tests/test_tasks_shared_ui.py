from __future__ import annotations

from html.parser import HTMLParser

import pytest

from project_workflow.interfaces.ui.templates import env
from tests.test_ui_shell_template import Elements


def task(**changes):
    record = {
        "task_key": "OWN-73", "namespace_id": 73, "namespace_name": "Owner namespace",
        "namespace_cli_command": "owner-command", "namespace_theme_color": "#123456",
        "namespace_theme_icon": "code", "workflow_name": "Owner workflow",
        "title": "Owner <title>", "current_phase_name": "Owner phase",
        "completed": 2, "total_phases": 5, "status": "active",
        "latest_verdict": "partial", "latest_verdict_label": "Owner <verdict>",
        "latest_verdict_phase": "Owner <review phase>", "created_at": "2026-10-23T10:15",
    }
    record.update(changes)
    return record


def render_tasks(records):
    return env.get_template("tasks.html").render(
        page="tasks", can_administer=False, tasks=records, ui_base_path=lambda: "/workflow",
        namespace_cookie_name="workflow_namespace_id", namespace_cookie_secure=False,
    )


class Definitions(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = []
        self.tag = None
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"dt", "dd"}:
            self.tag, self.parts = tag, []

    def handle_data(self, data):
        if self.tag:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == self.tag:
            self.values.append((tag, "".join(self.parts)))
            self.tag = None


@pytest.mark.parametrize("status,label,tone", [
    ("active", "В работе", "info"),
    ("blocked", "Заблокирована", "danger"),
    ("done", "Завершена", "success"),
])
def test_table_and_linked_card_share_owner_status_and_safe_task_identity(status, label, tone):
    html = render_tasks([task(status=status)])
    elements = Elements(html).elements
    links = [attrs for tag, attrs in elements if tag == "a" and
             attrs.get("href") == "/workflow/task/OWN-73?profession_id=73"]
    assert len(links) == 2
    assert sum("base-card" in attrs.get("class", "").split() for attrs in links) == 1
    assert sum("base-text-link" in attrs.get("class", "").split() for attrs in links) == 1
    assert all("onclick" not in attrs for attrs in links)
    assert html.count(f'data-tone="{tone}" data-appearance="badge">{label}</span>') == 2
    assert "Owner &lt;title&gt;" in html
    assert html.count("Owner &lt;verdict&gt;") == 2
    assert html.count('data-task-key="OWN-73"') == 2
    assert html.count('data-status="' + status + '"') == 2
    assert 'stroke="#123456"' in html
    definitions = Definitions(html).values
    assert definitions == [
        ("dt", "Профессия"), ("dd", "owner-command"),
        ("dt", "Флоу"), ("dd", "Owner workflow"),
        ("dt", "Фаза"), ("dd", "Owner phase"),
        ("dt", "Прогресс"), ("dd", "2/5"),
        ("dt", "Создана"), ("dd", "2026-10-23"),
    ]


def test_duplicate_titles_keep_distinct_namespace_urls_and_no_unrelated_selection():
    html = render_tasks([task(namespace_id=42), task(namespace_id=73)])
    links = [attrs for tag, attrs in Elements(html).elements if tag == "a"]
    for namespace_id in [42, 73]:
        assert sum(attrs.get("href") == f"/workflow/task/OWN-73?profession_id={namespace_id}"
                   for attrs in links) == 2
    assert html.count("Owner &lt;title&gt;") == 4


@pytest.mark.parametrize("completed,total,current", [(0, 0, None), (0, 5, "0"), (2, 5, "2"), (7, 5, "5")])
def test_progress_keeps_owner_counts_and_base_aria_normalization(completed, total, current):
    html = render_tasks([task(completed=completed, total_phases=total)])
    progress = next(attrs for _, attrs in Elements(html).elements if attrs.get("role") == "progressbar")
    assert progress.get("aria-valuenow") == current
    assert progress.get("aria-valuemax") == (str(total) if total else None)
    assert f"{completed}/{total}" in html
    assert progress["aria-valuetext"] == (f"{completed} из {total}" if total else "Фазы не заданы")


def test_empty_list_uses_two_common_states_for_responsive_presentations_without_records():
    html = render_tasks([])
    elements = Elements(html).elements
    assert sum(attrs.get("data-page-state") == "empty" for _, attrs in elements) == 2
    assert any(tag == "td" and attrs.get("colspan") == "9" for tag, attrs in elements)
    assert not any("data-task-key" in attrs for _, attrs in elements)


def test_unknown_verdict_keeps_label_and_uses_neutral_in_both_views():
    html = render_tasks([task(latest_verdict="future-result", latest_verdict_label="Owner future result")])
    assert html.count('data-tone="neutral" data-appearance="badge">Owner future result</span>') == 2


@pytest.mark.parametrize("required,denied,expected_role", [
    (True, False, None), (False, False, "alert"), (False, True, "alert"),
])
def test_sso_entry_uses_shared_screen_without_changing_result_or_owner_login_url(required, denied, expected_role):
    html = env.get_template("sso_entry.html").render(
        login_required=required, access_denied=denied, message="Owner <message>",
        login_url="/workflow/login?next=%2Ftask%2F73", platform_origin="https://portal.example.test",
    )
    elements = Elements(html).elements
    viewport = [attrs for tag, attrs in elements if tag == "meta" and attrs.get("name") == "viewport"]
    assert viewport == [{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
    main = [attrs for tag, attrs in elements if tag == "main"]
    assert len(main) == 1
    assert main[0]["class"] == "base-auth-screen"
    message = next(attrs for tag, attrs in elements if tag == "p" and
                   "base-auth-message" in attrs.get("class", "").split())
    assert message.get("role") == expected_role
    links = [attrs for tag, attrs in elements if tag == "a"]
    assert len(links) == (0 if denied else 1)
    if links:
        assert links[0]["href"] == "/workflow/login?next=%2Ftask%2F73"
        assert "base-button" in links[0]["class"].split()
    assert ("data-platform-login-required" in html) is required
    assert "Owner &lt;message&gt;" in html
    assert "font:16px system-ui" not in html
