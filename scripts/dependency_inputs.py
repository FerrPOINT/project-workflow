"""Canonical runtime dependency projection; package metadata stays in the app layer."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import tomllib


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--extra', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.project.open('rb') as stream:
        requirements = dependency_requirements(tomllib.load(stream), args.extra)
    args.output.write_text('\n'.join(requirements) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
