"""Every profession consumes participants' input and records its own actual contribution."""

import json

import pytest

from scripts.build_single_task_profile import render

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """Generator contracts read source files only; no UI database is involved."""
    yield


@pytest.fixture(scope="module")
def catalog():
    return json.loads(render()[0])


def test_all_eight_modes_read_complete_discussion_and_publish_after_evaluation_before_handoff(catalog):
    checked = []
    for workflow in catalog["workflows"]:
        for mode in workflow["modes"]:
            checked.append((workflow["role_key"], mode["key"]))
            first = mode["phases"][0]
            context = first["instructions"][1]["description"]
            for marker in ("ticket title/description", "every participant", "discussion read --task",
                           "next_after=null", "--after", "--snapshot", "same snapshot", "fresh scan"):
                assert marker in context, checked[-1]
            last = mode["phases"][-1]
            terminal = last["instructions"][-1]["description"]
            publish = terminal.index("discussion publish --task")
            readback = terminal.index("discussion operation --task")
            report = terminal.index("--report <report-text>")
            assert report < publish < readback
            for marker in ("work performed", "checks/evidence", "requested next", "FLEET_STAGE_COMMENT_KEY",
                           "PublishStageComment", "kind:pm", "kind:delivery", "body_sha256", "original key/body",
                           "changed or deleted", "do not claim the transition has already happened"):
                assert marker in terminal, checked[-1]
            criteria = " ".join(last["checks"] + last["evidence"])
            assert "Completion comment content" in criteria
            assert "Prepared completion summary" in criteria
            assert "Actual completion comment is saved" not in criteria
            assert "Workflow complete=true receipt" not in criteria
            assert "transition receipt" not in criteria
    assert len(checked) == 8


def test_rework_and_pm_consent_are_separate_from_writing_a_comment(catalog):
    for workflow in catalog["workflows"]:
        for mode in workflow["modes"]:
            terminal = mode["phases"][-1]["instructions"][-1]["description"]
            assert "does not grant owner consent" in terminal
            assert "A rework verdict must contain actionable findings" in terminal
            if workflow["role_key"] == "project_manager":
                assert terminal.index("exact owner confirmation receipt readback succeeds") < terminal.index(
                    "discussion publish --task",
                )
            else:
                assert terminal.index("discussion operation --task") < terminal.index("sdlc result propose --task")
                assert "After actual terminal, Fleet verifies" in terminal
