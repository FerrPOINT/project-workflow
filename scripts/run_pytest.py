"""Run pytest with an owned temporary tree and a recoverable run receipt."""

import json
import os
import shutil
import signal
import stat
import sys
import time
import uuid
from pathlib import Path

import pytest


def write_receipt(path: Path, value: dict) -> None:
    pending = path.with_suffix('.pending')
    with pending.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
    os.replace(pending, path)


def scratch_parent(directory: Path) -> Path:
    journal = os.environ.get('PDLC_FILE_OPERATION_JOURNAL')
    if not journal:
        return directory
    resource = json.loads(Path(journal).read_text(encoding='utf-8'))
    payload = Path(resource['path'])
    temporary = payload / 'tmp'
    marker = json.loads((payload / '.base-file-owner.json').read_text(encoding='utf-8'))
    if (resource['schema'] != 'base-file-resource/v1' or resource['phase'] != 'active'
            or marker != {'id': resource['id'], 'marker': resource['marker']}
            or os.environ.get('PDLC_OPERATION_DIR') != str(payload)
            or os.environ.get('TMPDIR') != str(temporary)
            or not temporary.is_dir() or temporary.resolve() != temporary):
        raise ValueError('Workflow pytest received an invalid Base managed operation')
    return temporary


def terminate(_signum, _frame):
    raise KeyboardInterrupt


def remove_scratch(scratch: Path) -> None:
    def retry_readonly_file(function, path, error):
        failure = error[1]
        if os.name != 'nt' or function is not os.unlink or not isinstance(failure, PermissionError):
            raise failure
        target = Path(path)
        info = target.lstat()
        if (not target.parent.resolve().is_relative_to(scratch)
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or not info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):
            raise failure
        target.chmod(stat.S_IWRITE)
        target.unlink()

    shutil.rmtree(scratch, onerror=retry_readonly_file)


def run(arguments: list[str], workspace: Path) -> int:
    if any(arg.split('=', 1)[0] in ('--basetemp', '--junitxml', '--junit-xml') for arg in arguments):
        raise ValueError('The Workflow runner owns pytest scratch and diagnostic output')
    local = workspace.resolve() / '.local'
    receipts = local / 'pytest-runs'
    fixtures = local / 'p'
    for directory in (local, receipts, fixtures):
        directory.mkdir(exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Workflow run storage must be a plain directory')
    operation = uuid.uuid4().hex
    directory = receipts / operation
    directory.mkdir(mode=0o700)
    parent = scratch_parent(fixtures)
    # Leave room for nested Git and catalog fixtures on Windows without changing
    # the full operation identity recorded in the receipt.
    scratch = parent / f'wf-{operation[:12]}'
    scratch.mkdir()
    report = directory / 'junit.xml'
    receipt = directory / 'result.json'
    record = {'schema': 'workflow-pytest-run/v1', 'operation': operation,
              'pid': os.getpid(), 'started_at': time.time(), 'status': 'active', 'scratch': str(scratch)}
    write_receipt(receipt, record)

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        code = int(pytest.main([*arguments, f'--basetemp={scratch}', f'--junitxml={report}',
                                '-o', 'junit_logging=no']))
    except KeyboardInterrupt:
        code = int(pytest.ExitCode.INTERRUPTED)
    finally:
        signal.signal(signal.SIGTERM, previous)

    # Unexpected termination leaves the active receipt and its owned tree intact.
    try:
        if scratch.exists() or scratch.is_symlink():
            remove_scratch(scratch)
        if report.exists() and (code == 0 or report.stat().st_size > 4 * 1024**2):
            report.unlink()
        record['cleanup'] = 'complete'
    except OSError as error:
        record['cleanup'] = 'recovery_required'
        record['cleanup_error'] = {'type': type(error).__name__, 'errno': error.errno,
                                   'winerror': getattr(error, 'winerror', None)}
    record.update(status='finished', exit_code=code, finished_at=time.time(),
                  diagnostic='junit.xml' if report.is_file() else None)
    write_receipt(receipt, record)
    print(f'Workflow pytest receipt: {receipt}', flush=True)
    return code if code or record['cleanup'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:], Path(__file__).resolve().parents[1]))
