"""Positive reviewed dependency closures, not a dev-package blacklist."""
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import tomllib

from scripts.dependency_inputs import dependency_locks

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'cpython-311-bookworm-amd64'


def inputs():
    return (tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8')),
            (ROOT / 'constraints.txt').read_text(encoding='utf-8'),
            json.loads((ROOT / 'dependency-wheels.json').read_text(encoding='utf-8')))


def locks(project, constraints, contract, target=TARGET):
    return dependency_locks(project, ['ui'], constraints, contract, target)


@pytest.mark.unit
def test_runtime_and_build_locks_cover_only_their_reachable_verified_wheels():
    project, constraints, contract = inputs()
    output = locks(project, constraints, contract)
    assert len(output['runtime'].splitlines()) == 37 + 2
    assert len(output['build'].splitlines()) == 6 + 2
    assert 'httpx==0.28.1 --hash=sha256:' in output['runtime']
    assert 'cryptography==50.0.1 --hash=sha256:' in output['runtime']
    assert 'hatchling==1.32.0 --hash=sha256:' in output['build']
    for kind, text in output.items():
        assert text.startswith('--only-binary=:all:\n--require-hashes\n')
        for name in ('pytest', 'coverage', 'mypy', 'ruff', 'httpx2'):
            assert '\n' + name + '==' not in text
        other = output['build' if kind == 'runtime' else 'runtime']
        assert set(text.splitlines()[2:]).isdisjoint(other.splitlines()[2:])


@pytest.mark.unit
def test_unselected_dev_pins_and_metadata_do_not_change_either_install_input():
    project, constraints, contract = inputs()
    expected = locks(project, constraints, contract)
    changed = deepcopy(project)
    changed['project']['version'] = '2.0.0'
    changed['project']['description'] = 'metadata-only'
    changed['project']['optional-dependencies']['dev'].append('new-dev-tool>=1')
    constraints = '# changed comment\n' + constraints.replace('ruff==0.16.4', 'ruff==0.17.0')
    constraints += '\nnew-dev-tool==1.0\n'
    assert locks(changed, constraints, contract) == expected


@pytest.mark.unit
@pytest.mark.parametrize('name,version', [('anyio', '4.14.2'), ('pycparser', '3.0'), ('hatchling', '1.32.0')])
def test_changed_runtime_transitive_or_build_pin_requires_new_metadata(name, version):
    project, constraints, contract = inputs()
    with pytest.raises(ValueError, match='Selected constraint changed'):
        locks(project, constraints.replace(name + '==' + version + '\n', name + '==999.0\n'), contract)


@pytest.mark.unit
@pytest.mark.parametrize('mutation', ['root', 'backend', 'missing', 'unreachable', 'hash', 'duplicate', 'target'])
def test_unknown_or_incomplete_dependency_contract_fails_before_install(mutation):
    project, constraints, contract = inputs()
    target = TARGET
    if mutation == 'root':
        project['project']['optional-dependencies']['ui'].append('new-runtime>=1')
    elif mutation == 'backend':
        project['build-system']['build-backend'] = 'other.build'
    elif mutation == 'missing':
        del contract['runtime']['packages']['pycparser']
    elif mutation == 'unreachable':
        contract['runtime']['packages']['unneeded'] = deepcopy(contract['runtime']['packages']['pycparser'])
    elif mutation == 'hash':
        contract['runtime']['packages']['pycparser']['wheel_sha256'] = 'not-a-digest'
    elif mutation == 'duplicate':
        constraints += '\nPyJWT==2.14.0\n'
    else:
        target = 'cpython-311-bookworm-arm64'
    with pytest.raises(ValueError):
        locks(project, constraints, contract, target)


@pytest.mark.unit
def test_cli_emits_the_same_locks_without_installer_or_environment_preparation(tmp_path):
    project, constraints, contract = inputs()
    runtime, build = tmp_path / 'runtime.txt', tmp_path / 'build.txt'
    result = subprocess.run([sys.executable, '-E', '-S', '-B', str(ROOT / 'scripts/dependency_inputs.py'),
                             '--project', str(ROOT / 'pyproject.toml'), '--extra', 'ui',
                             '--contract', str(ROOT / 'dependency-wheels.json'),
                             '--constraints', str(ROOT / 'constraints.txt'), '--target', TARGET,
                             '--output', str(runtime), '--build-output', str(build)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''
    assert {'runtime': runtime.read_text(), 'build': build.read_text()} == locks(project, constraints, contract)


@pytest.mark.unit
def test_coherently_removed_dependency_edge_cannot_bypass_reviewed_metadata():
    project, constraints, contract = inputs()
    contract['runtime']['packages']['cffi']['dependencies'].remove('pycparser')
    del contract['runtime']['packages']['pycparser']
    with pytest.raises(ValueError, match='Unreviewed wheel metadata contract'):
        locks(project, constraints, contract)


@pytest.mark.unit
def test_runtime_image_keeps_build_tools_out_of_the_final_venv():
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    digest = 'sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b'
    assert dockerfile.count(digest) == 4
    assert 'ENV PIP_CONSTRAINT=' not in dockerfile
    assert '--constraint /tmp/install-constraints.txt' in dockerfile
    assert 'pip wheel --no-build-isolation --no-deps' in dockerfile
    final = dockerfile.split(' AS runtime\n', 1)[1]
    assert 'COPY --from=runtime-inputs /opt/venv /opt/venv' in final
    assert '/opt/build-venv' not in final
    assert '/usr/local/lib/python3.11/site-packages' not in final
    assert 'pip uninstall -y pip setuptools wheel' in final
    assert 'COPY --from=builder /usr/local/bin' not in final


@pytest.mark.unit
@pytest.mark.parametrize('target,corrupt', [(TARGET, False), ('cpython-311-bookworm-arm64', False),
                                          ('cpython-311-bookworm-arm64', True)])
def test_cli_uses_full_legacy_constraints_only_for_an_explicit_unqualified_target(tmp_path, target, corrupt):
    project, constraints, contract = inputs()
    if corrupt:
        contract['build']['packages']['hatchling']['dependencies'] = []
    contract_path = tmp_path / 'contract.json'
    contract_path.write_text(json.dumps(contract), encoding='utf-8')
    runtime, build, install = (tmp_path / name for name in ('runtime.txt', 'build.txt', 'constraints.txt'))
    result = subprocess.run([sys.executable, '-E', '-S', '-B', str(ROOT / 'scripts/dependency_inputs.py'),
                             '--project', str(ROOT / 'pyproject.toml'), '--extra', 'ui',
                             '--contract', str(contract_path), '--constraints', str(ROOT / 'constraints.txt'),
                             '--target', target, '--allow-legacy-target', '--constraint-output', str(install),
                             '--output', str(runtime), '--build-output', str(build)],
                            capture_output=True, text=True, timeout=5)
    if corrupt:
        assert result.returncode != 0
        assert not runtime.exists() and not build.exists() and not install.exists()
    else:
        assert result.returncode == 0, result.stderr
        if target == TARGET:
            assert '# workflow-legacy-target:' not in install.read_text()
            assert 'ruff==' not in install.read_text()
            assert '--hash=sha256:' in runtime.read_text()
        else:
            assert install.read_text().endswith(constraints)
            assert install.read_text().startswith('# workflow-legacy-target: ' + target)
            assert 'retain full constraints' in result.stderr
            assert 'psycopg[binary]>=3.0' in runtime.read_text()
            assert build.read_text() == '\n'.join(project['build-system']['requires']) + '\n'
