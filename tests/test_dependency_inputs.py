"""Dependency layers ignore package metadata but retain the selected dependency graph."""
import re
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.dependency_inputs import dependency_requirements

ROOT = Path(__file__).resolve().parents[1]
UI_CRYPTO_RUNTIME = ('httpx', 'httpcore', 'pyjwt', 'cryptography', 'cffi', 'pycparser')


def constraint_name(line):
    return canonicalize_name(Requirement(line).name) if line.strip() and not line.lstrip().startswith('#') else None


def without_runtime_pins(constraints, names):
    return '\n'.join(line for line in constraints.splitlines() if constraint_name(line) not in names)


def runtime_pin_mismatches(constraints):
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    locked = {package['name']: package['version'] for package in lock['package']}
    pins = {}
    for line in constraints.splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            requirement = Requirement(line)
            pins[canonicalize_name(requirement.name)] = str(requirement.specifier)
    return {
        name for name in UI_CRYPTO_RUNTIME
        if pins.get(name) != '==' + locked[name]
    }


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


@pytest.mark.unit
def test_runtime_projection_selects_httpx_and_crypto_not_dev_httpx2():
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    selected = {
        canonicalize_name(requirement.name): requirement
        for value in dependency_requirements(data, ['ui'])
        for requirement in [Requirement(value)]
    }
    assert {'httpx', 'pyjwt'} <= selected.keys()
    assert selected['pyjwt'].extras == {'crypto'}
    assert 'httpx2' not in selected
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    packages = {package['name']: package for package in lock['package']}
    assert 'httpcore' in {edge['name'] for edge in packages['httpx']['dependencies']}
    assert 'cryptography' in {
        edge['name'] for edge in packages['pyjwt']['optional-dependencies']['crypto']
    }
    assert 'cffi' in {edge['name'] for edge in packages['cryptography']['dependencies']}
    assert 'pycparser' in {edge['name'] for edge in packages['cffi']['dependencies']}


@pytest.mark.unit
@pytest.mark.parametrize('name', UI_CRYPTO_RUNTIME)
def test_selected_ui_crypto_dependency_has_locked_runtime_constraint(name):
    constraints = (ROOT / 'constraints.txt').read_text(encoding='utf-8')
    assert name not in runtime_pin_mismatches(constraints), f'Missing locked runtime pin: {name}'


@pytest.mark.unit
@pytest.mark.parametrize('name', UI_CRYPTO_RUNTIME)
def test_removing_each_runtime_pin_is_detected(name):
    constraints = (ROOT / 'constraints.txt').read_text(encoding='utf-8')
    changed = without_runtime_pins(constraints, {name})
    assert runtime_pin_mismatches(changed) == {name}


@pytest.mark.unit
def test_dev_httpx2_constraints_cannot_satisfy_runtime_httpx():
    constraints = (ROOT / 'constraints.txt').read_text(encoding='utf-8')
    changed = without_runtime_pins(constraints, {'httpx', 'httpcore'})
    assert 'httpx2==' in changed and 'httpcore2==' in changed
    assert runtime_pin_mismatches(changed) == {'httpx', 'httpcore'}


@pytest.mark.unit
def test_runtime_pin_mutation_preserves_blank_and_comment_lines():
    constraints = '# Runtime constraints\n\n' + (ROOT / 'constraints.txt').read_text(encoding='utf-8')
    changed = without_runtime_pins(constraints, {'httpx'})
    assert changed.startswith('# Runtime constraints\n\n')
    assert runtime_pin_mismatches(constraints) == set()
    assert runtime_pin_mismatches(changed) == {'httpx'}


def docker_stages():
    recipe = (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text(encoding='utf-8')
    declarations = list(re.finditer(r'^FROM (\S+) AS (\S+)\n', recipe, re.MULTILINE))
    return {
        declaration[2]: (declaration[1], recipe[declaration.end():end])
        for declaration, end in zip(declarations, [item.start() for item in declarations[1:]] + [len(recipe)])
    }


@pytest.mark.unit
def test_wheel_inputs_exclude_runtime_tooling_without_hiding_package_inputs():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    # A hook, dynamic metadata or custom file selection needs a new input qualification.
    assert metadata['build-system'] == {'requires': ['hatchling==1.32.0'], 'build-backend': 'hatchling.build'}
    assert 'hatch' not in metadata.get('tool', {})
    assert not metadata['project'].get('dynamic')
    assert metadata['project']['name'].replace('-', '_') == 'project_workflow'
    assert metadata['project']['readme'] == 'README.md'
    assert metadata['project']['license-files'] == ['LICENSE']
    stages = docker_stages()
    parent, wheel = stages['wheel-inputs']
    assert parent == 'build-tools'
    assert 'ENV PYTHONDONTWRITEBYTECODE=1' in stages['build-tools'][1]
    assert re.findall(r'^COPY (.+)$', wheel, re.MULTILINE) == [
        'pyproject.toml README.md LICENSE ./', 'project_workflow/ ./project_workflow/',
    ]
    assert stages['builder'][0] == 'wheel-inputs'
    assert 'COPY ' not in stages['builder'][1]
    assert 'pip wheel --no-build-isolation --no-deps' in stages['builder'][1]
    assert stages['installed'][0] == 'runtime-dependencies'
    assert re.findall(r'^COPY (.+)$', stages['installed'][1], re.MULTILINE) == [
        '--from=builder /tmp/app-wheel/ /tmp/app-wheel/',
    ]
    assert 'pip install --no-compile --no-deps' in stages['installed'][1]
    assert stages['application-inputs'][0] == 'wheel-inputs'
    assert 'COPY scripts/ ./scripts/' in stages['application-inputs'][1]
    assert 'COPY alembic.ini constraints.txt ./' in stages['application-inputs'][1]


@pytest.mark.unit
def test_cached_wheel_still_requires_full_manifest_and_installed_compatibility():
    stages = docker_stages()
    assert stages['verified-inputs'][0] == 'application-inputs'
    verifier = stages['verified-inputs'][1]
    assert 'COPY runtime-*.json ./' in verifier
    assert verifier.index('verify-manifest') < verifier.index("&& printf 'verified\\n'")
    assert ('--mount=type=bind,from=verified-inputs,source=/tmp/runtime-inputs-verified,'
            'target=/tmp/runtime-inputs-verified,ro') in stages['builder'][1]
    # Inherit the installed/stripped venv: copying it onto runtime-dependencies would
    # merge directories and resurrect pip files removed by the builder.
    assert stages['runtime-inputs'][0] == 'installed'
    runtime_inputs = stages['runtime-inputs'][1]
    assert runtime_inputs.index('COPY --from=verified-inputs /app/ /app/') < runtime_inputs.index(
        '/opt/venv/bin/python -m scripts.build_runtime_image verify-compatibility --root /app')
    assert '/opt/venv' not in '\n'.join(re.findall(r'^COPY (.+)$', runtime_inputs, re.MULTILINE))
    copies = re.findall(r'^COPY --from=(\S+) (\S+) (\S+)$', stages['runtime'][1], re.MULTILINE)
    assert copies == [
        ('runtime-inputs', path, path) for path in (
            '/opt/venv', '/app/alembic.ini', '/app/scripts',
            '/app/project_workflow/infrastructure/db/migrations',
            '/app/runtime-build-manifest.json', '/app/runtime-compatibility.json',
        )
    ]
