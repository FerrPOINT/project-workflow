"""Reviewed source-only archive controls: tiny Git fixtures, no Docker/DB."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import py_compile
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from project_workflow.build_provenance import BuildProvenanceError


def _run_git(
    root: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_bytes,
        check=True,
        capture_output=True,
    )


def _builder_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_runtime_image.py"
    spec = importlib.util.spec_from_file_location("build_runtime_image_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def git_source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    files = {
        "LICENSE": b"license\n",
        "README.md": b"line-one\nline-two\n",
        "alembic.ini": b"[alembic]\n",
        "constraints.txt": b"click==8.1.8\n",
        "pyproject.toml": b"[project]\nname='fixture'\n",
        "Dockerfile": b"FROM scratch\n",
        "runtime-build-manifest.json": b'{"schema_version":0,"status":"unavailable"}\n',
        ".gitignore": b"project_workflow/injected.py\n",
        "project_workflow/source.py": b"VALUE = 1\n",
        "scripts/source.py": b"print('source')\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "fixture@example.invalid")
    _run_git(root, "config", "user.name", "Fixture")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "fixture")
    return root


def _member_bytes(archive: bytes, path: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as source:
        member = source.getmember(path)
        fileobj = source.extractfile(member)
        assert fileobj is not None
        return fileobj.read()


def test_controlled_snapshot_ignores_external_attributes_and_mutable_refs(git_source: Path):
    builder = _builder_module()
    (git_source / 'version.txt').write_bytes(b'$Format:%H$\n$Format:%d$\n')
    (git_source / '.gitattributes').write_text('version.txt export-subst\n')
    _run_git(git_source, 'add', '.')
    _run_git(git_source, 'commit', '-m', 'pinned attributes')
    before = builder.immutable_git_snapshot(git_source, 'HEAD')
    (git_source / '.git/info/attributes').write_text('project_workflow/source.py export-ignore\n')
    _run_git(git_source, 'branch', 'new-decoration', before.revision)
    assert builder.immutable_git_snapshot(git_source, before.revision) == before
    assert _member_bytes(before.archive, 'project_workflow/source.py') == b'VALUE = 1\n'


def test_controlled_metadata_ignores_ambient_git_directory(git_source: Path):
    builder = _builder_module()
    before = builder.immutable_git_snapshot(git_source, 'HEAD')
    with patch.dict(os.environ, {'GIT_DIR': str(git_source / 'missing'),
                               'GIT_OBJECT_DIRECTORY': str(git_source / 'missing-objects')}):
        assert builder.immutable_git_snapshot(git_source, before.revision) == before


def test_vendor_loader_ignores_a_valid_poisoned_pyc_and_rejects_changed_source(tmp_path: Path):
    builder = _builder_module()
    root = Path(__file__).resolve().parents[1]
    fake = tmp_path / 'checkout'
    vendor = fake / 'scripts/vendor'
    vendor.mkdir(parents=True)
    source = vendor / 'base_controlled_git_archive.py'
    original = (root / 'scripts/vendor/base_controlled_git_archive.py').read_bytes()
    poisoned = original.replace(b'base-object-store-archive/v1', b'fake-object-store-archive/v1')
    assert len(poisoned) == len(original) and poisoned != original
    source.write_bytes(poisoned)
    (vendor / 'base-controlled-git-archive.json').write_bytes(
        (root / 'scripts/vendor/base-controlled-git-archive.json').read_bytes())
    # This fixture writes a cache deliberately. Keep that cache beside its own
    # temporary source instead of appending a long global cache-prefix path.
    with patch.object(sys, 'pycache_prefix', None):
        py_compile.compile(str(source), doraise=True)
        info = source.stat()
        source.write_bytes(original)
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        spec = importlib.util.spec_from_file_location('poisoned_archive_fixture', source)
        assert spec and spec.loader
        ordinary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ordinary)
        assert ordinary.POLICY == 'fake-object-store-archive/v1'
    with patch.object(builder, '__file__', str(fake / 'scripts/build_runtime_image.py')):
        component, stamp = builder._archive_component()
        assert component.POLICY == 'base-object-store-archive/v1'
        assert stamp[0] == hashlib.sha256(original).hexdigest()
        source.write_bytes(original + b"\nraise AssertionError('must not execute')\n")
        with pytest.raises(BuildProvenanceError, match='exact Base descriptor'):
            builder._archive_component()


def test_pinned_package_git_reader_ignores_foreign_git_environment(git_source: Path):
    from project_workflow.infrastructure import base_package
    revision = _run_git(git_source, 'rev-parse', 'HEAD').stdout.decode().strip()
    with patch.dict(os.environ, {'GIT_DIR': str(git_source / 'missing'),
                               'GIT_OBJECT_DIRECTORY': str(git_source / 'missing-objects')}):
        actual = base_package.git(git_source, 'show', revision + ':project_workflow/source.py')
    assert actual == b'VALUE = 1\n'
