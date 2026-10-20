"""Pure recipe guards without importing the legacy database fixture graph."""
import re
from pathlib import Path

import pytest
import tomllib


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



@pytest.mark.unit
def test_manifest_and_compatibility_keep_existing_catalog_and_oci_identity():
    stages = docker_stages()
    verified = stages['verified-inputs'][1]
    final = stages['runtime'][1]
    for option, variable in [('source-revision', 'SOURCE_REVISION'),
                             ('source-archive-sha256', 'SOURCE_ARCHIVE_SHA256'),
                             ('runtime-bundle-sha256', 'RUNTIME_BUNDLE_SHA256')]:
        assert '--' + option + ' "$' + variable + '"' in verified
    for label in ['org.opencontainers.image.revision=$SOURCE_REVISION',
                  'io.relevanter.source.archive-sha256=$SOURCE_ARCHIVE_SHA256',
                  'io.relevanter.runtime.bundle-sha256=$RUNTIME_BUNDLE_SHA256']:
        assert label in final
    for name in ['runtime-inputs', 'runtime']:
        assert 'ARG CATALOG_VARIANT="legacy"' in stages[name][1]
        assert 'ENV PROJECT_WORKFLOW_CATALOG_VARIANT=${CATALOG_VARIANT}' in stages[name][1]
    assert 'ENV PYTHONDONTWRITEBYTECODE=1' in stages['build-tools'][1]
    assert 'ENV PYTHONDONTWRITEBYTECODE=1' in final
