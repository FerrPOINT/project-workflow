"""Canonical runtime dependency projection; package metadata stays in the app layer."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import tomllib

# New metadata/target graphs need explicit source review before narrowing input.
WHEEL_CONTRACT_SHA256 = '2d6ef9bb9dfdae8c576dde52020bbf3c3cd25d8d71709fed4f7ff0f4841e11b7'


def reviewed_contract(contract: dict[str, Any]) -> None:
    encoded = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if (contract.get('schema') != 'workflow-wheel-inputs/v1'
            or hashlib.sha256(encoded).hexdigest() != WHEEL_CONTRACT_SHA256):
        raise ValueError('Unreviewed wheel metadata contract; qualify the changed graph')


def dependency_requirements(value: dict[str, Any], extras: list[str]) -> list[str]:
    project = value.get('project', {})
    if set(project.get('dynamic', [])) & {'dependencies', 'optional-dependencies'}:
        raise ValueError('Dynamic dependency metadata needs a qualified projection')
    groups = [project.get('dependencies')]
    optional = project.get('optional-dependencies', {})
    for extra in extras:
        if extra not in optional:
            raise ValueError('Unknown dependency extra: ' + extra)
        groups.append(optional[extra])
    requirements = set()
    for group in groups:
        if not isinstance(group, list) or not all(
            isinstance(item, str) and item and not item.startswith('-') and '\n' not in item and '\r' not in item
            for item in group
        ):
            raise ValueError('Static dependency requirement lists are required')
        requirements.update(group)
    return sorted(requirements)


def dependency_locks(value: dict[str, Any], extras: list[str], constraints: str,
                     contract: dict[str, Any], target: str) -> dict[str, str]:
    """Emit exact reviewed wheel closures without invoking an installer/resolver.

    Canonical versions stay in constraints; the contract records observed wheel
    metadata, selected dependency edges and artifact hashes, not alternate pins.
    """
    if contract.get('schema') != 'workflow-wheel-inputs/v1' or target != contract.get('target'):
        raise ValueError('Unreviewed dependency target; qualify its exact wheel closure')
    reviewed_contract(contract)
    pins = {}
    for line in constraints.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)', line.strip())
        if not match:
            raise ValueError('Dependency projection requires plain exact constraint pins')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in pins:
            raise ValueError('Duplicate constraint: ' + name)
        pins[name] = match[2]
    expected = {'runtime': dependency_requirements(value, extras),
                'build': sorted(value.get('build-system', {}).get('requires', []))}
    if value.get('build-system') != contract.get('build_system'):
        raise ValueError('Build backend changed; qualify its dependency closure')
    outputs = {}
    for kind, requirements in expected.items():
        group = contract[kind]
        if group['requirements'] != requirements:
            raise ValueError(kind + ' dependency roots changed; refresh the reviewed closure')
        roots = set()
        for requirement in requirements:
            name = re.match(r'[A-Za-z0-9][A-Za-z0-9._-]*', requirement)
            if not name or ';' in requirement:
                raise ValueError('Conditional roots need an explicit target contract')
            roots.add(re.sub(r'[-_.]+', '-', name[0]).lower())
        packages = group['packages']
        reachable, pending = set(), list(roots)
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            if name not in packages:
                raise ValueError('Missing reviewed dependency: ' + name)
            reachable.add(name)
            pending.extend(packages[name]['dependencies'])
        if reachable != set(packages):
            raise ValueError('Unreachable packages must not enter the ' + kind + ' payload')
        lines = ['--only-binary=:all:', '--require-hashes']
        for name in sorted(reachable):
            package = packages[name]
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or pins.get(name) != package['version']:
                raise ValueError('Selected constraint changed; refresh wheel metadata: ' + name)
            for field in ('wheel_sha256', 'metadata_sha256'):
                if not re.fullmatch(r'[0-9a-f]{64}', package[field]):
                    raise ValueError('Missing exact wheel/metadata digest: ' + name)
            lines.append(name + '==' + pins[name] + ' --hash=sha256:' + package['wheel_sha256'])
        outputs[kind] = '\n'.join(lines) + '\n'
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--extra', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--contract', type=Path)
    parser.add_argument('--constraints', type=Path)
    parser.add_argument('--target')
    parser.add_argument('--build-output', type=Path)
    parser.add_argument('--constraint-output', type=Path)
    parser.add_argument('--allow-legacy-target', action='store_true')
    args = parser.parse_args()
    with args.project.open('rb') as stream:
        project = tomllib.load(stream)
    if args.contract:
        if not all((args.constraints, args.target, args.build_output)):
            parser.error('--contract requires --constraints, --target and --build-output')
        constraints = args.constraints.read_text(encoding='utf-8')
        contract = json.loads(args.contract.read_text(encoding='utf-8'))
        reviewed_contract(contract)
        if args.allow_legacy_target and args.target != contract['target']:
            if not args.constraint_output or project.get('build-system') != contract['build_system']:
                parser.error('Legacy target requires full constraint output and the reviewed build backend')
            outputs = {'runtime': '\n'.join(dependency_requirements(project, args.extra)) + '\n',
                       'build': '\n'.join(sorted(project['build-system']['requires'])) + '\n'}
            install_constraints = '# workflow-legacy-target: ' + args.target + '\n' + constraints
            print('Unqualified wheel target; retain full constraints: ' + args.target, file=sys.stderr)
        else:
            outputs = dependency_locks(project, args.extra, constraints, contract, args.target)
            install_constraints = '# Exact versions and wheel hashes are in requirement files.\n'
        args.output.write_text(outputs['runtime'], encoding='utf-8')
        args.build_output.write_text(outputs['build'], encoding='utf-8')
        if args.constraint_output:
            args.constraint_output.write_text(install_constraints, encoding='utf-8')
    else:
        if any((args.constraints, args.target, args.build_output, args.constraint_output, args.allow_legacy_target)):
            parser.error('Wheel projection options require --contract')
        requirements = dependency_requirements(project, args.extra)
        args.output.write_text('\n'.join(requirements) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
