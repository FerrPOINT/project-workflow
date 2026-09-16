"""Regression tests for the large UI smoke-data fixture."""

from types import SimpleNamespace


def test_workflow_ids_omit_unsaved_workflows() -> None:
    from scripts.bulk_ui_smoke_data import _workflow_ids

    workflows = [SimpleNamespace(id=1), SimpleNamespace(id=None), SimpleNamespace(id=3)]

    assert _workflow_ids(workflows) == [1, 3]
