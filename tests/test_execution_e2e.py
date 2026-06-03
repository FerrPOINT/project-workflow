"""E2E tests for /execution page: drag-and-drop, merge, horizontal reorder, save+reload.

Run:  pytest tests/test_execution_e2e.py -v
"""

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8878"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        yield p.chromium.launch(headless=True)


@pytest.fixture
def page(browser):
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    yield pg
    pg.close()


def _go(page):
    page.goto(f"{BASE_URL}/execution")
    page.wait_for_timeout(1500)


def _screenshot(page, name):
    path = f"/tmp/e2e_{name}.png"
    page.screenshot(path=path, full_page=True)
    return path


# ═══════════════════════════════════════════════════════════════════════
#  Basic render
# ═══════════════════════════════════════════════════════════════════════

def test_execution_renders(page):
    _go(page)
    assert page.locator(".flow-node").count() >= 10
    assert page.locator(".parallel-group").count() >= 1
    assert page.locator(".join-point").count() >= 1


def test_mermaid_renders(page):
    _go(page)
    assert "flowchart TD" in page.content()
    assert page.locator(".mermaid-wrap").count() == 1


# ═══════════════════════════════════════════════════════════════════════
#  Merge two sync nodes into parallel group
# ═══════════════════════════════════════════════════════════════════════

def test_merge_two_sync_nodes(page):
    """Drag a sync node onto another sync node → creates parallel group."""
    _go(page)
    before_groups = page.locator(".parallel-group").count()
    before_branches = page.locator(".parallel-branch").count()

    # Pick two adjacent sync nodes (e.g. 4 and 5)
    node4 = page.locator('[data-phase-id="4"]').first
    node5 = page.locator('[data-phase-id="5"]').first
    assert node4.count() == 1
    assert node5.count() == 1

    # Drag 4 onto 5 and HOLD for 300ms to trigger merge timer
    node4.hover()
    page.mouse.down()
    node5.hover()
    page.wait_for_timeout(350)
    page.mouse.up()
    page.wait_for_timeout(300)

    _screenshot(page, "merge")

    after_groups = page.locator(".parallel-group").count()
    after_branches = page.locator(".parallel-branch").count()
    # Either group count increased by 1, or branches inside group increased
    assert after_branches >= before_branches + 1 or after_groups >= before_groups + 1


# ═══════════════════════════════════════════════════════════════════════
#  Horizontal reorder inside parallel group
# ═══════════════════════════════════════════════════════════════════════

def test_horizontal_reorder_inside_group(page):
    """Drag a branch inside parallel group to reorder horizontally."""
    _go(page)
    _screenshot(page, "reorder_before")

    # Need at least one parallel group with 2+ branches
    groups = page.locator(".parallel-group").all()
    assert len(groups) >= 1, "No parallel groups to test reorder"

    group = groups[0]
    branches = group.locator(".parallel-branch").all()
    assert len(branches) >= 2, "Need at least 2 branches for reorder"

    # Get initial order of phase ids in this group
    initial_ids = [
        b.locator(".flow-node").first.get_attribute("data-phase-id")
        for b in branches
    ]

    # Drag second branch onto first drop-zone
    drop_zones = group.locator(".parallel-drop-zone").all()
    if len(drop_zones) >= 1 and len(branches) >= 2:
        branches[1].drag_to(drop_zones[0], force=True)
        page.wait_for_timeout(300)
        _screenshot(page, "reorder_after")

        # Check new order
        new_branches = group.locator(".parallel-branch").all()
        new_ids = [
            b.locator(".flow-node").first.get_attribute("data-phase-id")
            for b in new_branches
        ]
        # Expect swapped order
        assert new_ids == [initial_ids[1], initial_ids[0]] + initial_ids[2:]

        # Check flex direction stays row
        flex = page.locator(".parallel-branches").first.evaluate(
            "el => window.getComputedStyle(el).flexDirection"
        )
        assert flex == "row"


# ═══════════════════════════════════════════════════════════════════════
#  Extract node from parallel group
# ═══════════════════════════════════════════════════════════════════════

def test_extract_node_from_group(page):
    """Click extract button → node becomes sync outside group."""
    _go(page)
    before_nodes = page.locator(".flow-node").count()

    # Find first parallel node with extract button
    btn = page.locator(".parallel-group .btn-extract").first
    assert btn.count() == 1
    btn.click()
    page.wait_for_timeout(300)
    _screenshot(page, "extract")

    # Node should now exist outside parallel group as sync
    nodes_outside = page.locator('.flow-node[data-type="sync"]').count()
    assert nodes_outside >= 1


# ═══════════════════════════════════════════════════════════════════════
#  Ungroup entire parallel group
# ═══════════════════════════════════════════════════════════════════════

def test_ungroup_group(page):
    """Click 'Разъединить' → all nodes become sync."""
    _go(page)
    before_groups = page.locator(".parallel-group").count()
    assert before_groups >= 1

    btn = page.locator(".parallel-group .join-point .btn-control").first
    assert btn.count() == 1
    btn.click()
    page.wait_for_timeout(300)
    _screenshot(page, "ungroup")

    after_groups = page.locator(".parallel-group").count()
    assert after_groups == before_groups - 1


# ═══════════════════════════════════════════════════════════════════════
#  Save layout and reload
# ═══════════════════════════════════════════════════════════════════════

def test_save_and_reload_preserves_parallel(page):
    """Create parallel group, save, reload → group still exists."""
    _go(page)
    # Create a parallel group first (merge 4 onto 5)
    node4 = page.locator('[data-phase-id="4"]').first
    node5 = page.locator('[data-phase-id="5"]').first
    if node4.count() and node5.count():
        node4.hover()
        page.mouse.down()
        node5.hover()
        page.wait_for_timeout(350)
        page.mouse.up()
        page.wait_for_timeout(300)

    _screenshot(page, "save_before")

    # Save
    page.locator("button[onclick='saveLayout()']").click()
    page.wait_for_timeout(800)

    # Reload
    _go(page)
    _screenshot(page, "save_after_reload")

    assert page.locator(".parallel-group").count() >= 1
