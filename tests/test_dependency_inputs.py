"""Dependency layers ignore package metadata but retain the selected dependency graph."""
from copy import deepcopy

import pytest

from scripts.dependency_inputs import dependency_requirements


def project():
    return {'project': {'name': 'fixture', 'version': '1.0.0', 'dependencies': ['requests>=2', 'click>=8'],
                        'optional-dependencies': {'ui': ['fastapi>=0.100'], 'dev': ['pytest>=9']},
                        'scripts': {'fixture': 'fixture:main'}}}


@pytest.mark.unit
def test_metadata_and_unselected_extras_do_not_invalidate_runtime_dependencies():
    original = project()
    changed = deepcopy(original)
    changed['project']['version'] = '2.0.0'
    changed['project']['scripts'] = {'new': 'fixture:new'}
    changed['project']['optional-dependencies']['dev'] = ['pytest>=10']
    assert dependency_requirements(original, ['ui']) == dependency_requirements(changed, ['ui'])
    assert dependency_requirements(original, ['ui']) == ['click>=8', 'fastapi>=0.100', 'requests>=2']


@pytest.mark.unit
def test_selected_dependencies_and_extras_are_real_inputs():
    original = project()
    changed = deepcopy(original)
    changed['project']['optional-dependencies']['ui'] = ['fastapi>=0.141']
    assert dependency_requirements(original, ['ui']) != dependency_requirements(changed, ['ui'])
    assert dependency_requirements(original, []) == ['click>=8', 'requests>=2']


@pytest.mark.unit
@pytest.mark.parametrize('bad', [None, 'requests>=2', ['--index-url=https://example.test'], ['click>=8\nunsafe']])
def test_unqualified_dependency_projection_fails_closed(bad):
    data = project()
    data['project']['dependencies'] = bad
    with pytest.raises(ValueError):
        dependency_requirements(data, ['ui'])


@pytest.mark.unit
def test_dynamic_or_missing_extra_requires_explicit_qualification():
    data = project()
    data['project']['dynamic'] = ['dependencies']
    with pytest.raises(ValueError):
        dependency_requirements(data, ['ui'])
    with pytest.raises(ValueError):
        dependency_requirements(project(), ['missing'])
