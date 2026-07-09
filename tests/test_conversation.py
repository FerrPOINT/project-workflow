"""Tests for conversation.py SQLite persistence."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure import conversation as convo


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    """Point conversation DB to temp path for each test."""
    monkeypatch.setattr(convo, "DB_PATH", tmp_path / "convo" / "conversation.db")


def test_add_and_get_messages():
    convo.add_message("t1", "AAT-1", "user", "started", phase_id="0.00", tags="note")
    convo.add_message("t1", "AAT-1", "system", "moved", phase_id="0.01", tags="transition")
    messages = convo.get_messages("t1")
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].phase_id == "0.00"


def test_get_messages_with_filters():
    convo.add_message("t2", "AAT-2", "user", "note text", tags="note")
    convo.add_message("t2", "AAT-2", "system", "transition text", tags="transition")
    notes = convo.get_messages("t2", tags="note")
    assert len(notes) == 1
    assert notes[0].tags == "note"

    by_phase = convo.get_messages("t2", phase_id="0.99")
    assert by_phase == []


def test_message_to_dict():
    convo.add_message("t3", "AAT-3", "wizard", "question", phase_id="0.00", tags="question")
    msg = convo.get_messages("t3")[0]
    d = msg.to_dict()
    assert d["role"] == "wizard"
    assert d["task_key"] == "AAT-3"
    assert "id" in d
    assert "created_at" in d


def test_limit():
    for i in range(5):
        convo.add_message("t4", "AAT-4", "user", f"msg {i}")
    assert len(convo.get_messages("t4", limit=2)) == 2
    assert len(convo.get_messages("t4")) == 5
