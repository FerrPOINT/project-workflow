"""Tests for conversation.py SQLite persistence."""
from __future__ import annotations


import pytest

from project_workflow import conversation as convo


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point conversation DB to temp path for each test."""
    monkeypatch.setattr(convo, "DB_DIR", tmp_path / "convo")
    monkeypatch.setattr(convo, "DB_PATH", tmp_path / "convo" / "conversation.db")
    # close any cached state
    return convo


class TestEnsureDb:
    def test_ensure_db_creates_directory(self, tmp_db, tmp_path):
        assert not (tmp_path / "convo").exists()
        conn = tmp_db._ensure_db()
        assert (tmp_path / "convo").exists()
        conn.close()

    def test_ensure_db_idempotent(self, tmp_db):
        conn1 = tmp_db._ensure_db()
        conn1.close()
        conn2 = tmp_db._ensure_db()
        conn2.close()


class TestAddMessage:
    def test_add_message_returns_id(self, tmp_db):
        msg_id = tmp_db.add_message("t1", "TASK-1", "user", "hello")
        assert msg_id > 0

    def test_add_user_note(self, tmp_db):
        _ = tmp_db.add_user_note("t1", "TASK-1", "report")
        msgs = tmp_db.get_messages("t1")
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].tags == "note"

    def test_add_phase_transition(self, tmp_db):
        tmp_db.add_phase_transition("t1", "TASK-1", "1", "2")
        msgs = tmp_db.get_messages("t1", tags="transition")
        assert len(msgs) == 1
        assert "2" in msgs[0].content
        assert msgs[0].phase_id == "2"

    def test_add_wizard_question_and_answer(self, tmp_db):
        tmp_db.add_wizard_question("t1", "TASK-1", "2", "Done?")
        tmp_db.add_wizard_answer("t1", "TASK-1", "2", "Yes", ok=True)
        msgs = tmp_db.get_messages("t1")
        assert any(m.role == "wizard" for m in msgs)
        assert any(m.tags == "pass" for m in msgs)


class TestGetMessages:
    def test_get_messages_order(self, tmp_db):
        tmp_db.add_message("t1", "TASK-1", "user", "first")
        tmp_db.add_message("t1", "TASK-1", "system", "second")
        msgs = tmp_db.get_messages("t1")
        assert [m.content for m in msgs] == ["first", "second"]

    def test_get_messages_limit(self, tmp_db):
        for i in range(10):
            tmp_db.add_message("t1", "TASK-1", "user", f"msg{i}")
        msgs = tmp_db.get_messages("t1", limit=3)
        assert len(msgs) == 3
        # get_messages applies ORDER BY id DESC + reversed(rows) => latest 3 in chronological order
        assert [m.content for m in msgs] == ["msg7", "msg8", "msg9"]

    def test_get_messages_filter_phase(self, tmp_db):
        tmp_db.add_message("t1", "TASK-1", "user", "a", phase_id="1")
        tmp_db.add_message("t1", "TASK-1", "user", "b", phase_id="2")
        msgs = tmp_db.get_messages("t1", phase_id="1")
        assert len(msgs) == 1
        assert msgs[0].content == "a"

    def test_get_messages_filter_tags(self, tmp_db):
        tmp_db.add_message("t1", "TASK-1", "user", "note1", tags="note")
        tmp_db.add_message("t1", "TASK-1", "user", "note2", tags="note,important")
        tmp_db.add_message("t1", "TASK-1", "user", "other", tags="other")
        msgs = tmp_db.get_messages("t1", tags="note")
        assert len(msgs) == 2

    def test_get_latest_user_notes(self, tmp_db):
        tmp_db.add_message("t1", "TASK-1", "system", "s")
        tmp_db.add_message("t1", "TASK-1", "user", "u1", tags="note")
        tmp_db.add_message("t1", "TASK-1", "user", "u2", tags="note")
        notes = tmp_db.get_latest_user_notes("t1")
        assert len(notes) == 2

    def test_get_messages_empty(self, tmp_db):
        assert tmp_db.get_messages("missing") == []


class TestLastPhaseAndKeywords:
    def test_get_last_phase(self, tmp_db):
        assert tmp_db.get_last_phase("t1") is None
        tmp_db.add_message("t1", "TASK-1", "user", "x", phase_id="2")
        tmp_db.add_message("t1", "TASK-1", "user", "y", phase_id="3")
        assert tmp_db.get_last_phase("t1") == "3"

    def test_check_keyword_in_history(self, tmp_db):
        tmp_db.add_message("t1", "TASK-1", "user", "hello world")
        assert tmp_db.check_keyword_in_history("t1", "world")
        assert not tmp_db.check_keyword_in_history("t1", "missing")


class TestBuildStatusDigest:
    def test_build_status_digest(self, tmp_db):
        tmp_db.add_phase_transition("t1", "TASK-1", "1", "2")
        tmp_db.add_user_note("t1", "TASK-1", "progress updated")
        digest = tmp_db.build_status_digest("t1", "TASK-1")
        assert digest["task_id"] == "t1"
        assert digest["task_key"] == "TASK-1"
        assert digest["transitions_count"] == 1
        assert digest["total_messages"] == 2
        assert digest["has_progress"] is True

    def test_build_status_digest_current_phase_override(self, tmp_db):
        tmp_db.add_phase_transition("t1", "TASK-1", "1", "2")
        digest = tmp_db.build_status_digest("t1", "TASK-1", current_phase="3")
        assert digest["last_phase"] == "3"


class TestMessageDataclass:
    def test_message_to_dict(self):
        m = convo.Message(
            id=1, task_id="t1", task_key="TASK-1", role="user",
            content="hello", phase_id="1", tags="note", created_at="now"
        )
        d = m.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "hello"
        assert d["phase_id"] == "1"
