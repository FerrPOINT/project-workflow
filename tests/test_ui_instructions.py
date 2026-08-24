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
    def test_reorder_templates_move_rows_and_restore_dom_on_failure(self):
        phase_id = _seed_phase_id()
        dedicated = client.get(f"/instructions?phase_id={phase_id}").text
        detail = client.get(f"/phase/{phase_id}").text

        assert "layout.replaceChildren(...reordered)" in dedicated
        assert "layout.replaceChildren(...rows)" in dedicated
        assert "appendChild(r.closest('.instruction-block')" not in dedicated
        assert "const isParallelGroup = group.length > 1;" in dedicated
        assert "type === 'parallel' ? ' parallel-group'" not in dedicated
        assert "if (!await persistInstructionOrder())" in detail
        assert "renderInstructionTimeline(items)" in detail

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
        current_ids = [
            item["id"]
            for item in client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"]
        ]
        full_order = [item_id for item_id in current_ids if item_id not in ids] + reversed_ids

        response = client.put(
            f"/api/phases/{phase_id}/instructions/reorder",
            json={"instruction_ids": full_order},
        )
        assert response.status_code == 200

        listed = client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"]
        listed_ids = [item["id"] for item in listed if item["id"] in ids]
        assert listed_ids == reversed_ids

        for item in items:
            client.delete(f"/api/instructions/{item['id']}")

    def test_reorder_404_for_missing_phase(self):
        response = client.put("/api/phases/9999999/instructions/reorder", json={"instruction_ids": [9999999]})
        assert response.status_code == 404

    @pytest.mark.parametrize("instruction_ids", [[], [1, 1], ["1"], [True]])
    def test_reorder_rejects_malformed_ids(self, instruction_ids):
        phase_id = _seed_phase_id()
        response = client.put(
            f"/api/phases/{phase_id}/instructions/reorder",
            json={"instruction_ids": instruction_ids},
        )
        assert response.status_code == 422

    def test_reorder_rejects_incomplete_missing_and_cross_phase_ids(self):
        phase_id = _seed_phase_id()
        other_phase_id = client.get("/api/phases").json()["phases"][1]["id"]
        own_ids = [
            item["id"]
            for item in client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"]
        ]
        foreign = client.post(
            "/api/instructions",
            json={"phase_id": other_phase_id, "description": "foreign instruction"},
        ).json()["instruction"]

        incomplete = own_ids[:-1] if len(own_ids) > 1 else [9999998]
        assert client.put(
            f"/api/phases/{phase_id}/instructions/reorder",
            json={"instruction_ids": incomplete},
        ).status_code == 409
        assert client.put(
            f"/api/phases/{phase_id}/instructions/reorder",
            json={"instruction_ids": own_ids[:-1] + [9999999]},
        ).status_code == 409
        assert client.put(
            f"/api/phases/{phase_id}/instructions/reorder",
            json={"instruction_ids": own_ids[:-1] + [foreign["id"]]},
        ).status_code == 409
        client.delete(f"/api/instructions/{foreign['id']}")

    def test_delete_instruction_keeps_contiguous_step_numbers(self):
        phase_id = _seed_phase_id()
        created = [
            client.post(
                "/api/instructions",
                json={"phase_id": phase_id, "description": f"delete-order-{index}"},
            ).json()["instruction"]["id"]
            for index in range(3)
        ]
        for instruction_id in (created[0], created[1], created[2]):
            assert client.delete(f"/api/instructions/{instruction_id}").status_code == 200
            rows = client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"]
            assert [row["step_num"] for row in rows] == list(range(1, len(rows) + 1))

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

    def test_create_instruction_inserts_at_requested_step(self):
        phase_id = _seed_phase_id()
        appended = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "append marker"},
        ).json()["instruction"]

        response = client.post(
            "/api/instructions",
            json={
                "phase_id": phase_id,
                "description": "insert marker",
                "step_num": appended["step_num"],
            },
        )

        assert response.status_code == 200
        inserted = response.json()["instruction"]
        listed = client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"]
        positions = {item["description"]: item["step_num"] for item in listed}
        assert positions["insert marker"] == appended["step_num"]
        assert positions["append marker"] == appended["step_num"] + 1

        client.delete(f"/api/instructions/{inserted['id']}")
        client.delete(f"/api/instructions/{appended['id']}")

    def test_create_instruction_rejects_step_past_end(self):
        phase_id = _seed_phase_id()
        count = len(client.get(f"/api/phases/{phase_id}/instructions").json()["instructions"])

        response = client.post(
            "/api/instructions",
            json={"phase_id": phase_id, "description": "out of range", "step_num": count + 2},
        )

        assert response.status_code == 422


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
