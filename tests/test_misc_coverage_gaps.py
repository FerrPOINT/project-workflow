"""Coverage gap tests for small leftover branches."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]


def test_repositories_compat_module_imports():
    from project_workflow import infrastructure

    assert hasattr(infrastructure, "db")
