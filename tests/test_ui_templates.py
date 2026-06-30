"""Tests for interfaces.ui.templates filters."""
from __future__ import annotations

from markupsafe import Markup

from project_workflow.interfaces.ui.templates import _group_instructions, _pluralize, _tojson_unicode


def test_tojson_unicode():
    result = _tojson_unicode({"key": "значение"})
    assert isinstance(result, Markup)
    assert "значение" in result
    assert '"key"' in result


def test_group_instructions_filter():
    assert _group_instructions(None) == []
    assert _group_instructions([]) == []
    a = {"id": 1, "execution_type": "sync"}
    b = {"id": 2, "execution_type": "parallel"}
    c = {"id": 3, "execution_type": "sync"}
    assert _group_instructions([a, b, c]) == [[a, b], [c]]


def test_pluralize():
    assert _pluralize(1, "проект,проекта,проектов") == "1 проект"
    assert _pluralize(2, "проект,проекта,проектов") == "2 проекта"
    assert _pluralize(5, "проект,проекта,проектов") == "5 проектов"
    assert _pluralize(11, "проект,проекта,проектов") == "11 проектов"
    assert _pluralize(21, "проект,проекта,проектов") == "21 проект"
    assert _pluralize(22, "проект,проекта,проектов") == "22 проекта"
    assert _pluralize(25, "проект,проекта,проектов") == "25 проектов"
