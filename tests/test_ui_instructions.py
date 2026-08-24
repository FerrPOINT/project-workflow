"""Tests for instruction management API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui import app

client = TestClient(app)


def _seed_phase_id() -> int:
    """Return the first available phase id after setup."""
    response = client.get("/api/phases")
    assert response.status_code == 200
    phases = response.json()["phases"]
    assert phases
    return int(phases[0]["id"])


class TestInstructionsApi:
    def test_instructions_list_returns_phase_and_instructions(self):
        phase_id = _seed_phase_id()
        response = client.get(f"/api/phases/{phase_id}/instructions")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["phase"]["id"] == phase_id
        assert isinstance(data["instructions"], list)

    def test_instructions_list_404_for_missing_phase(self):
        response = client.get("/api/phases/9999999/instructions")
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_create_instruction(self):
        phase_id = _seed_phase_id()
        response = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "New test instruction", "execution_type": "sync"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        item = data["instruction"]
        assert item["phase_id"] == phase_id
        assert item["description"] == "New test instruction"
        assert item["execution_type"] == "sync"
        assert isinstance(item["step_num"], int)

        # Cleanup
        client.delete(f"/api/instructions/{item['id']}")

    def test_create_instruction_requires_phase(self):
        response = client.post("/api/instructions", json={"description": "orphan"})
        assert response.status_code == 422

    def test_update_instruction_description_and_parallel(self):
        phase_id = _seed_phase_id()
        create = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "before"},
        )
        item = create.json()["instruction"]

        update = client.put(
            f"/api/instructions/{item['id']}",
            json={"description": "after", "execution_type": "parallel"},
        )
        assert update.status_code == 200
        updated = update.json()["instruction"]
        assert updated["description"] == "after"
        assert updated["execution_type"] == "parallel"

        client.delete(f"/api/instructions/{item['id']}")

    def test_update_instruction_404(self):
        response = client.put("/api/instructions/9999999", json={"description": "x"})
        assert response.status_code == 404

    def test_delete_instruction(self):
        phase_id = _seed_phase_id()
        create = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "to delete"},
        )
        item = create.json()["instruction"]
        response = client.delete(f"/api/instructions/{item['id']}")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_delete_instruction_404(self):
        response = client.delete("/api/instructions/9999999")
        assert response.status_code == 404

    def test_reorder_instructions(self):
        phase_id = _seed_phase_id()
        items = [
            client.post("/api/instructions", json={"phase_id": phase_id, "description": f"i{n}"}).json()["instruction"]
            for n in range(3)
        ]
        ids = [item["id"] for item in items]
        reversed_ids = list(reversed(ids))

        response = client.put(
            f"/api/phases/{phase_id}/instructions/reorder",
            json={"instruction_ids": reversed_ids},
        )
        assert response.status_code == 200

        listed = client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"]
        listed_ids = [item["id"] for item in listed if item["id"] in ids]
        assert listed_ids == reversed_ids

        for item in items:
            client.delete(f"/api/instructions/{item['id']}")

    def test_reorder_404_for_missing_phase(self):
        response = client.put("/api/phases/9999999/instructions/reorder", json={"instruction_ids": []})
        assert response.status_code == 404

    def test_create_instruction_persists_skills(self):
        phase_id = _seed_phase_id()
        response = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "with skills", "skills": ["a", "b"]},
        )
        item = response.json()["instruction"]
        assert set(item["skills"]) == {"a", "b"}
        client.delete(f"/api/instructions/{item['id']}")

    def test_update_instruction_skills_omitted_null_empty_and_list(self):
        phase_id = _seed_phase_id()
        create = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "x", "skills": ["keep"]},
        )
        item = create.json()["instruction"]
        omitted = client.put(f"/api/instructions/{item['id']}", json={"description": "updated"})
        assert omitted.json()["instruction"]["skills"] == ["keep"]

        cleared = client.put(f"/api/instructions/{item['id']}", json={"skills": None})
        assert cleared.json()["instruction"]["skills"] == []
        replaced = client.put(f"/api/instructions/{item['id']}", json={"skills": ["one", "two"]})
        assert replaced.json()["instruction"]["skills"] == ["one", "two"]
        emptied = client.put(f"/api/instructions/{item['id']}", json={"skills": []})
        assert emptied.json()["instruction"]["skills"] == []
        rejected = client.put(
            f"/api/instructions/{item['id']}",
            json={"skills": "one\ntwo"},
        )
        assert rejected.status_code == 422
        client.delete(f"/api/instructions/{item['id']}")


class TestInstructionsPage:
    def test_instructions_page_requires_phase_id(self):
        response = client.get("/instructions")
        assert response.status_code == 400

    def test_instructions_page_renders_existing_phase(self):
        phase_id = _seed_phase_id()
        response = client.get(f"/instructions?phase_id={phase_id}")
        assert response.status_code == 200
        assert "instructions.html" in response.text or "instruction" in response.text.lower()

    def test_instructions_page_404_for_missing_phase(self):
        response = client.get("/instructions?phase_id=9999999")
        assert response.status_code == 404

    def test_instructions_page_removed_legacy_path(self):
        phase_id = _seed_phase_id()
        response = client.get(f"/phase/{phase_id}/instructions")
        assert response.status_code == 404
