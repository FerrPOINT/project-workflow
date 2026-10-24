"""Opt-in exact-object archive, independent of checkout config and mutable refs.

Standalone stdlib module. Callers own source selection, policy adoption and the
returned payload. The temporary bare repository shares only read-only objects;
its config, attributes, HEAD and refs are private and deterministic.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import tempfile

POLICY = 'base-object-store-archive/v1'
MAX_ARCHIVE_BYTES = 64 * 1024**2
OPTIONS = ('--no-replace-objects', '--literal-pathspecs', '--no-pager',
           '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
           '-c', 'core.attributesfile=' + os.devnull, '-c', 'tar.umask=0022')


class ControlledGitError(ValueError):
    pass


def environment():
    value = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    value.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                 GIT_CONFIG_SYSTEM=os.devnull, GIT_ATTR_NOSYSTEM='1',
                 GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0',
                 GIT_NO_LAZY_FETCH='1', LC_ALL='C', LANG='C', TZ='UTC')
    return value


def _plain(path, *, directory=False):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ControlledGitError('Controlled Git path must not traverse a link')
    if directory and not path.is_dir():
        raise ControlledGitError('Controlled Git directory is unavailable')
    return path


def _text(path, *, allow_empty=False):
    path = _plain(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise ControlledGitError('Controlled Git administration pointer is invalid')
    value = path.read_bytes().decode('utf-8').strip()
    if (not value and not allow_empty) or '\n' in value or '\r' in value or '\0' in value:
        raise ControlledGitError('Controlled Git administration pointer is invalid')
    return value


def object_store(checkout, *, admin_boundary=None):
    root = _plain(checkout, directory=True)
    boundary = _plain(admin_boundary or root, directory=True)
    marker = root / '.git'
    if marker.is_dir():
        gitdir = _plain(marker, directory=True)
    elif marker.is_file():
        value = _text(marker)
        if not value.startswith('gitdir: '):
            raise ControlledGitError('Controlled Git checkout pointer is invalid')
        gitdir = Path(os.path.abspath(root / value[8:]))
    else:
        raise ControlledGitError('Controlled Git requires an explicit source checkout')
    if not gitdir.is_relative_to(boundary):
        raise ControlledGitError('Controlled Git administration leaves its declared boundary')
    gitdir = _plain(gitdir, directory=True)
    common = gitdir
    pointer = gitdir / 'commondir'
    if pointer.exists() or pointer.is_symlink():
        common = Path(os.path.abspath(gitdir / _text(pointer)))
    if not common.is_relative_to(boundary):
        raise ControlledGitError('Controlled Git common directory leaves its declared boundary')
    objects = _plain(common / 'objects', directory=True)
    for name in ('alternates', 'http-alternates'):
        path = objects / 'info' / name
        if path.exists() or path.is_symlink():
            if _text(path, allow_empty=True):
                raise ControlledGitError('Controlled Git object alternates are unsupported')
    return objects


def _tool():
    executable = shutil.which('git', path=environment().get('PATH'))
    if not executable:
        raise ControlledGitError('Controlled Git executable is unavailable')
    executable = _plain(Path(executable).resolve())
    try:
        version = subprocess.check_output([str(executable), '--version'], env=environment(),
                                         stderr=subprocess.DEVNULL, timeout=10).decode('utf-8').strip()
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise ControlledGitError('Controlled Git version is unavailable') from error
    return {'executable': str(executable), 'sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'version': version}


def identity():
    tool = _tool()
    return {'policy': POLICY, 'host': os.name, 'machine': platform.machine(),
            'git': {name: tool[name] for name in ('sha256', 'version')}}


def canonical_archive(checkout, revision, paths=(), *, admin_boundary=None,
                      max_bytes=MAX_ARCHIVE_BYTES):
    """Return a bounded archive; no checkout ref/config/attribute can alter it.

    Output is collected in one disposable file before its bounded read, so a
    large Git stdout is not first buffered in Python. max_bytes bounds returned
    bytes, not an OS-enforced temporary disk quota or measured process memory.
    """
    if not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{40}', revision):
        raise ControlledGitError('Controlled Git archive requires an exact commit')
    if isinstance(paths, (str, bytes)):
        raise ControlledGitError('Controlled Git archive requires a path list')
    paths = tuple(paths)
    for name in paths:
        if (not isinstance(name, str) or not name or name.startswith('-')
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name
                or any(c in name for c in ('\\', ':', '\n', '\r', '\0'))):
            raise ControlledGitError('Controlled Git archive path leaves the pinned tree')
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_ARCHIVE_BYTES:
        raise ControlledGitError('Controlled Git archive byte budget is invalid')
    objects = object_store(checkout, admin_boundary=admin_boundary)
    executable = _tool()['executable']
    clean = environment()
    with tempfile.TemporaryDirectory(prefix='base-object-store-archive-') as temporary:
        owned = Path(temporary).resolve()
        if owned.parent != Path(tempfile.gettempdir()).resolve():
            raise ControlledGitError('Controlled Git scratch allocation leaves its owner')
        bare, empty = owned / 'repository.git', owned / 'empty-template'
        empty.mkdir()
        try:
            subprocess.run([executable, *OPTIONS, 'init', '--bare', '--quiet', '--object-format=sha1',
                            '--template=' + str(empty), str(bare)], cwd=owned,
                           env=clean, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           timeout=30, check=True)
            (bare / 'HEAD').write_text(revision + '\n', encoding='ascii')
            archive_env = {**clean, 'GIT_OBJECT_DIRECTORY': str(objects)}
            prefix = [executable, *OPTIONS, '--git-dir=' + str(bare)]
            kind = subprocess.check_output([*prefix, 'cat-file', '-t', revision], cwd=owned,
                env=archive_env, stderr=subprocess.PIPE, timeout=10).strip()
            if kind != b'commit':
                raise ControlledGitError('Controlled Git archive requires a commit object')
            with tempfile.TemporaryFile(dir=owned) as output:
                subprocess.run([*prefix, 'archive', '--format=tar', revision, '--', *paths],
                    cwd=owned, env=archive_env, stdout=output, stderr=subprocess.PIPE,
                    timeout=60, check=True)
                if output.tell() > max_bytes:
                    raise ControlledGitError('Controlled Git archive exceeds its byte budget')
                output.seek(0)
                payload = output.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise ControlledGitError('Controlled Git archive exceeds its byte budget')
                return payload
        except (OSError, UnicodeError, subprocess.SubprocessError) as error:
            raise ControlledGitError('Controlled Git archive failed; source objects were not changed') from error
