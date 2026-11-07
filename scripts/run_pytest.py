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


def run(arguments: list[str], workspace: Path) -> int:
    if any(arg.split('=', 1)[0] in ('--basetemp', '--junitxml', '--junit-xml') for arg in arguments):
        raise ValueError('The Workflow runner owns pytest scratch and diagnostic output')
    base = workspace.resolve()
    for name in ('.local', 'pytest-runs'):
        base /= name
        base.mkdir(exist_ok=True)
        info = base.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Workflow run storage must be a plain directory')
    operation = uuid.uuid4().hex
    directory = base / operation
    directory.mkdir(mode=0o700)
    parent = scratch_parent(directory)
    scratch = parent / ('pytest' if parent == directory else f'workflow-pytest-{operation}')
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
            shutil.rmtree(scratch)
        if report.exists() and (code == 0 or report.stat().st_size > 4 * 1024**2):
            report.unlink()
        record['cleanup'] = 'complete'
    except OSError:
        record['cleanup'] = 'recovery_required'
    record.update(status='finished', exit_code=code, finished_at=time.time(),
                  diagnostic='junit.xml' if report.is_file() else None)
    write_receipt(receipt, record)
    print(f'Workflow pytest receipt: {receipt}', flush=True)
    return code if code or record['cleanup'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:], Path(__file__).resolve().parents[1]))
