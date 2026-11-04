"""Rejected CP1 evidence remains a stopped experiment, not a live qualification."""

import json
from pathlib import Path


def test_rejected_cp1_preserves_six_calls_and_unexecuted_later_checkpoints():
    path = Path(__file__).resolve().parents[1] / "docs/evidence/advisor-v18-checkpoints-20261104.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["qualified"] is False
    assert saved["status"] == "stopped_cp1"
    assert saved["attempted_calls"] == 6 and saved["max_http_calls"] == 48
    assert len(saved["slots"]) == 48
    completed = saved["slots"][:6]
    assert [(item["case_id"], item["variant"]) for item in completed] == [
        ("actual-pm-189", "old"), ("actual-pm-189", "new"),
        ("actual-pm-190", "old"), ("actual-pm-190", "new"),
        ("actual-pm-191", "old"), ("actual-pm-191", "new")]
    assert [item["status"] for item in completed] == [
        "matched", "matched", "classification_mismatch", "matched",
        "classification_mismatch", "classification_mismatch"]
    assert sum(len(item["diagnostics"]["response"]["assessments"]) for item in completed) == 36
    assert all(item["diagnostics"]["provider"]["http_status"] == 200 for item in completed)
    assert all(item["diagnostics"]["provider"]["finish_reason"] == "stop" for item in completed)
    assert all(item["diagnostics"]["prompt"]["truncated"] is False for item in completed)
    assert all(item["status"] == "not_run" for item in saved["slots"][6:])
