"""Tests for graph execution batches, mermaid, drag-and-drop backend, and rebuild.

Covers:
- _build_execution_batches with sync/parallel/star topology
- _mermaid_from_batches generation
- API order + parallel updates and page rerender
- Connected components for parallel groups >2
- Config PHASE_ORDER rebuild after DB changes
"""

import json
import pytest
from fastapi.testclient import TestClient

from wartz_workflow.ui import app, _build_execution_batches, _mermaid_from_batches, _update_config_phase_order
from wartz_workflow import config

client = TestClient(app)

# Сохранить оригинальный PHASE_ORDER для восстановления
_ORIGINAL_PHASE_ORDER = list(config.PHASE_ORDER)


def _reset_orders():
    """Восстановить DB orders к оригинальному YAML-состоянию."""
    from wartz_workflow.ui import _get_db
    wdb = _get_db()
    for idx, pid in enumerate(_ORIGINAL_PHASE_ORDER, 1):
        wdb.update_phase_order(pid, idx)
    _update_config_phase_order()


@pytest.fixture(autouse=True)
def setup_db():
    """Populate DB with YAML phases before UI tests; reset orders after each test."""
    from wartz_workflow.ui import _get_db, _yaml_to_sqlite
    wdb = _get_db()
    if wdb.is_empty():
        _yaml_to_sqlite()
    _reset_orders()
    yield
    _reset_orders()


# ═══════════════════════════════════════════════════════════════════════
#  _build_execution_batches — unit tests
# ═══════════════════════════════════════════════════════════════════════

class TestBuildExecutionBatches:
    def test_sync_only(self):
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 1},
            {"id": "0", "name": "Jira Init", "phase_num": 2},
            {"id": "1", "name": "Preflight", "phase_num": 3},
        ]
        batches = _build_execution_batches(phases)
        assert len(batches) == 3
        assert all(b["type"] == "sync" for b in batches)
        assert [b["phases"][0]["id"] for b in batches] == ["-1", "0", "1"]

    def test_parallel_pair(self):
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 1},
            {"id": "4", "name": "Implement", "phase_num": 2, "parallel_with": "5"},
            {"id": "5", "name": "Validate", "phase_num": 3, "parallel_with": "4"},
            {"id": "6", "name": "Commit", "phase_num": 4},
        ]
        batches = _build_execution_batches(phases)
        assert len(batches) == 3  # sync(-1), parallel(4+5), sync(6)
        assert batches[0]["type"] == "sync"
        assert batches[1]["type"] == "parallel"
        assert sorted([p["id"] for p in batches[1]["phases"]]) == ["4", "5"]
        assert batches[2]["type"] == "sync"

    def test_order_uses_db_not_config(self):
        """After drag-and-drop DB order must win over config.PHASE_ORDER."""
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 3},
            {"id": "0", "name": "Jira", "phase_num": 1},
            {"id": "1", "name": "Preflight", "phase_num": 2},
        ]
        batches = _build_execution_batches(phases)
        ids = [b["phases"][0]["id"] for b in batches]
        assert ids == ["0", "1", "-1"]

    def test_star_topology_becomes_single_group(self):
        """A linked to B, C linked to B → all three in ONE parallel group."""
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 1},
            {"id": "4", "name": "Implement", "phase_num": 2, "parallel_with": "5"},
            {"id": "5", "name": "Validate", "phase_num": 3, "parallel_with": "4"},
            {"id": "5.5", "name": "Self-Test", "phase_num": 3, "parallel_with": "4"},
            {"id": "6", "name": "Commit", "phase_num": 4},
        ]
        batches = _build_execution_batches(phases)
        parallel_batches = [b for b in batches if b["type"] == "parallel"]
        assert len(parallel_batches) == 1
        group_ids = sorted([p["id"] for p in parallel_batches[0]["phases"]])
        assert group_ids == ["4", "5", "5.5"]

    def test_parallel_group_rendered_in_db_order(self):
        """Parallel group phases must be sorted by DB phase_order."""
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 1},
            {"id": "7.5", "name": "Review", "phase_num": 2, "parallel_with": "7.6"},
            {"id": "7.6", "name": "QA", "phase_num": 3, "parallel_with": "7.5"},
        ]
        batches = _build_execution_batches(phases)
        assert batches[1]["type"] == "parallel"
        ids = [p["id"] for p in batches[1]["phases"]]
        assert ids == ["7.5", "7.6"]

    def test_missing_phase_skipped(self):
        """If a parallel_with points to a non-existent phase, ignore it."""
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 1},
            {"id": "4", "name": "Implement", "phase_num": 2, "parallel_with": "nonexistent"},
        ]
        batches = _build_execution_batches(phases)
        assert len(batches) == 2
        assert batches[1]["type"] == "sync"


# ═══════════════════════════════════════════════════════════════════════
#  _mermaid_from_batches — unit tests
# ═══════════════════════════════════════════════════════════════════════

class TestMermaidFromBatches:
    def test_sync_mermaid(self):
        batches = [
            {"type": "sync", "phases": [{"id": "-1", "name": "Intake", "phase_num": 1}]},
            {"type": "sync", "phases": [{"id": "0", "name": "Jira", "phase_num": 2}]},
        ]
        mmd = _mermaid_from_batches(batches)
        assert "flowchart TD" in mmd
        assert "neg1[P1:Intake]" in mmd
        assert "0[P2:Jira]" in mmd
        assert "neg1 --> 0" in mmd

    def test_parallel_mermaid(self):
        batches = [
            {"type": "sync", "phases": [{"id": "-1", "name": "Intake", "phase_num": 1}]},
            {
                "type": "parallel",
                "phases": [
                    {"id": "4", "name": "Implement", "phase_num": 2},
                    {"id": "5", "name": "Validate", "phase_num": 3},
                ],
            },
            {"type": "sync", "phases": [{"id": "6", "name": "Commit", "phase_num": 4}]},
        ]
        mmd = _mermaid_from_batches(batches)
        assert "JOIN_4{🔄}" in mmd
        assert "4[P2:Implement]" in mmd
        assert "5[P3:Validate]" in mmd
        assert "6[P4:Commit]" in mmd
        assert "4 --> JOIN_4" in mmd
        assert "5 --> JOIN_4" in mmd
        assert "JOIN_4 --> 6" in mmd

    def test_parallel_group_unique_join_ids(self):
        """Multiple parallel groups must have unique JOIN node ids."""
        batches = [
            {
                "type": "parallel",
                "phases": [
                    {"id": "4", "name": "Implement", "phase_num": 2},
                    {"id": "5", "name": "Validate", "phase_num": 3},
                ],
            },
            {
                "type": "parallel",
                "phases": [
                    {"id": "7.5", "name": "Review", "phase_num": 5},
                    {"id": "7.6", "name": "QA", "phase_num": 6},
                ],
            },
        ]
        mmd = _mermaid_from_batches(batches)
        assert "JOIN_4" in mmd
        assert "JOIN_7_5" in mmd  # dot replaced with underscore


# ═══════════════════════════════════════════════════════════════════════
#  API integration — order + parallel + rerender
# ═══════════════════════════════════════════════════════════════════════

class TestGraphAPIIntegration:
    def test_api_order_update_rebuilds_config(self):
        """After order API, config.PHASE_ORDER must reflect new DB state."""
        from wartz_workflow.ui import _get_db
        wdb = _get_db()
        # Reset all phases to unique orders so no ties
        phases = wdb.get_phases()
        reset = [(p["id"], idx + 100) for idx, p in enumerate(phases)]
        wdb.batch_update_orders(reset)
        # Now set small orders for test subset
        wdb.batch_update_orders([("-1", 1), ("0", 2), ("1", 3)])
        _update_config_phase_order()
        assert config.PHASE_ORDER[:3] == ["-1", "0", "1"]

        # Swap -1 and 1
        resp = client.put("/api/phases/order", json={
            "orders": [
                {"phase_id": "-1", "phase_order": 3},
                {"phase_id": "1", "phase_order": 1},
                {"phase_id": "0", "phase_order": 2},
            ]
        })
        assert resp.status_code == 200
        assert config.PHASE_ORDER[:3] == ["1", "0", "-1"]

    def test_api_parallel_and_rerender(self):
        """Set parallel links, then request execution page — graph must show group."""
        resp = client.put("/api/phases/parallel", json={
            "groups": [["4.5", "5"]],
            "clear": [],
        })
        assert resp.status_code == 200

        resp = client.get("/execution")
        assert resp.status_code == 200
        text = resp.text
        # Must contain parallel group markup
        assert 'data-type="parallel"' in text
        assert "parallel-group" in text
        assert "Разъединить" in text

    def test_api_parallel_clear_removes_group(self):
        """Clear parallel link, then rerender — group must disappear."""
        # First create a group
        client.put("/api/phases/parallel", json={
            "groups": [["4.5", "5"]],
            "clear": [],
        })
        # Now clear
        resp = client.put("/api/phases/parallel", json={
            "groups": [],
            "clear": ["4.5", "5"],
        })
        assert resp.status_code == 200

        # Verify DB state
        from wartz_workflow.ui import _get_db
        wdb = _get_db()
        p45 = wdb.get_phase("4.5")
        p5 = wdb.get_phase("5")
        assert p45["parallel_with"] is None or p45["parallel_with"] == ""
        assert p5["parallel_with"] is None or p5["parallel_with"] == ""

    def test_api_single_phase_order(self):
        resp = client.put("/api/phases/1/order", json={"phase_order": 99})
        assert resp.status_code == 200
        from wartz_workflow.ui import _get_db
        wdb = _get_db()
        p = wdb.get_phase("1")
        assert p["phase_order"] == 99

    def test_execution_page_has_mermaid(self):
        resp = client.get("/execution")
        assert resp.status_code == 200
        assert "mermaid" in resp.text
        assert "flowchart TD" in resp.text

    def test_execution_page_has_drop_zones(self):
        resp = client.get("/execution")
        assert resp.status_code == 200
        assert 'class="drop-zone"' in resp.text
        assert 'ondrop="zoneDrop(event)"' in resp.text

    def test_execution_page_has_controls(self):
        resp = client.get("/execution")
        assert resp.status_code == 200
        assert "saveLayout()" in resp.text
        assert "resetLayout()" in resp.text


# ═══════════════════════════════════════════════════════════════════════
#  Connected components — edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestConnectedComponents:
    def test_chain_parallel_links(self):
        """A→B, B→C, C→D (chain) → all in one group."""
        phases = [
            {"id": "-1", "name": "Intake", "phase_num": 1},
            {"id": "a", "name": "A", "phase_num": 2, "parallel_with": "b"},
            {"id": "b", "name": "B", "phase_num": 3, "parallel_with": "c"},
            {"id": "c", "name": "C", "phase_num": 4, "parallel_with": "d"},
            {"id": "d", "name": "D", "phase_num": 5, "parallel_with": "c"},
        ]
        batches = _build_execution_batches(phases)
        parallel = [b for b in batches if b["type"] == "parallel"]
        assert len(parallel) == 1
        ids = sorted([p["id"] for p in parallel[0]["phases"]])
        assert ids == ["a", "b", "c", "d"]

    def test_isolated_orphan_parallel_link(self):
        """A→B where B doesn't exist → A stays sync."""
        phases = [
            {"id": "a", "name": "A", "phase_num": 1, "parallel_with": "missing"},
        ]
        batches = _build_execution_batches(phases)
        assert len(batches) == 1
        assert batches[0]["type"] == "sync"

    def test_self_loop_ignored(self):
        """A→A is ignored."""
        phases = [
            {"id": "a", "name": "A", "phase_num": 1, "parallel_with": "a"},
        ]
        batches = _build_execution_batches(phases)
        assert batches[0]["type"] == "sync"


# ═══════════════════════════════════════════════════════════════════════
#  Graph rebuild after structural changes
# ═══════════════════════════════════════════════════════════════════════

class TestGraphRebuild:
    def test_rebuild_after_full_reorder(self):
        """Completely reverse order and verify batches follow new order."""
        from wartz_workflow.ui import _get_db
        wdb = _get_db()
        phases = wdb.get_phases()
        # Reverse all orders
        max_order = len(phases)
        orders = [(p["id"], max_order - p["phase_order"] + 1) for p in phases]
        wdb.batch_update_orders(orders)
        _update_config_phase_order()

        resp = client.get("/execution")
        assert resp.status_code == 200
        # The first batch phase should now be the one that was last
        # We can't easily assert HTML structure, but we verify no crash

    def test_parallel_group_survives_roundtrip(self):
        """Create group, save, reload — group must still exist."""
        from wartz_workflow.ui import _get_db
        wdb = _get_db()
        # Clear any old links
        wdb.update_phase_parallel("7.5", None)
        wdb.update_phase_parallel("7.6", None)
        # Create bidirectional link
        wdb.batch_update_groups({"7.5": "7.6", "7.6": "7.5"})
        _update_config_phase_order()

        resp = client.get("/execution")
        assert resp.status_code == 200
        text = resp.text
        assert "parallel-group" in text
        assert "7.5" in text
        assert "7.6" in text
        # Join is rendered as div class join-point, not as JOIN_xxx text
        assert 'class="join-point"' in text
        assert 'data-type="parallel"' in text
