import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RunPytestTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows readonly attribute')
    def test_readonly_hardlink_keeps_external_file_unchanged(self):
        from scripts.run_pytest import remove_scratch

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            scratch = root / 'scratch'
            scratch.mkdir()
            external = root / 'external'
            external.write_bytes(b'outside fixture')
            (scratch / 'link').hardlink_to(external)
            external.chmod(stat.S_IREAD)
            try:
                with self.assertRaises(PermissionError):
                    remove_scratch(scratch)
                self.assertFalse(external.stat().st_mode & stat.S_IWRITE)
                self.assertEqual(external.read_bytes(), b'outside fixture')
            finally:
                external.chmod(stat.S_IWRITE)

    def test_success_failure_and_interrupt_leave_only_selected_evidence(self):
        source = Path(__file__).resolve().parents[2]
        env = {**os.environ, 'PYTHONPATH': str(source), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
        for key in ('PYTEST_ADDOPTS', 'PDLC_FILE_OPERATION_JOURNAL'):
            env.pop(key, None)
        for statement, expected in (('pass', 0), ('assert False', 1), ('raise KeyboardInterrupt', 2)):
            with self.subTest(statement=statement), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'test_example.py').write_text(
                    'import stat\n\n'
                    'def test_example(tmp_path):\n'
                    '    fixture = tmp_path / "fixture.db"\n'
                    '    fixture.write_bytes(b"fixture")\n'
                    '    fixture.chmod(stat.S_IREAD)\n'
                    f'    {statement}\n', encoding='utf-8',
                )
                result = subprocess.run(
                    [sys.executable, '-B', '-c',
                     'from pathlib import Path; from scripts.run_pytest import run; '
                     'raise SystemExit(run(["-q", "test_example.py"], Path.cwd()))'],
                    cwd=root, env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                paths = list((root / '.local' / 'pytest-runs').glob('*/result.json'))
                self.assertEqual(len(paths), 1)
                receipt = json.loads(paths[0].read_text(encoding='utf-8'))
                self.assertEqual((receipt['status'], receipt['cleanup'], receipt['exit_code']),
                                 ('finished', 'complete', expected))
                self.assertFalse(Path(receipt['scratch']).exists())
                self.assertEqual((paths[0].parent / 'junit.xml').is_file(), expected != 0)

    def test_process_loss_preserves_active_receipt_and_owned_fixture(self):
        source = Path(__file__).resolve().parents[2]
        env = {**os.environ, 'PYTHONPATH': str(source), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
        for key in ('PYTEST_ADDOPTS', 'PDLC_FILE_OPERATION_JOURNAL'):
            env.pop(key, None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'test_lost.py').write_text(
                'import os\n\n'
                'def test_lost(tmp_path):\n'
                '    (tmp_path / "fixture.db").write_bytes(b"fixture")\n'
                '    os._exit(137)\n',
                encoding='utf-8',
            )
            result = subprocess.run(
                [sys.executable, '-B', '-c',
                 'from pathlib import Path; from scripts.run_pytest import run; '
                 'raise SystemExit(run(["-q", "test_lost.py"], Path.cwd()))'],
                cwd=root, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 137, result.stdout + result.stderr)
            paths = list((root / '.local' / 'pytest-runs').glob('*/result.json'))
            self.assertEqual(len(paths), 1)
            receipt = json.loads(paths[0].read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'], 'active')
            self.assertNotIn('exit_code', receipt)
            scratch = Path(receipt['scratch'])
            self.assertEqual(scratch.parent, root.resolve() / '.local' / 'p')
            self.assertEqual(scratch.name, f'wf-{receipt["operation"][:12]}')
            fixtures = list(scratch.rglob('fixture.db'))
            self.assertEqual(len(fixtures), 1)
            self.assertEqual(fixtures[0].read_bytes(), b'fixture')


class RunStorageTests(unittest.TestCase):
    def test_owned_pytest_paths_cannot_be_overridden(self):
        from scripts.run_pytest import run

        for argument in ('--basetemp=elsewhere', '--basetemp', '--junitxml=outside.xml', '--junit-xml'):
            with self.subTest(argument=argument), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaisesRegex(ValueError, 'owns pytest scratch'):
                    run([argument], root)
                self.assertFalse((root / '.local').exists())

    @unittest.skipUnless(hasattr(os, 'symlink') and os.name != 'nt', 'POSIX symlink fixture')
    def test_foreign_storage_link_is_rejected_without_touching_target(self):
        from scripts.run_pytest import run

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, foreign = root / 'workspace', root / 'foreign'
            workspace.mkdir()
            foreign.mkdir()
            marker = foreign / 'keep.txt'
            marker.write_text('unrelated data', encoding='utf-8')
            (workspace / '.local').symlink_to(foreign, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'plain directory'):
                run([], workspace)
            self.assertEqual(marker.read_text(encoding='utf-8'), 'unrelated data')
            self.assertEqual(list(foreign.iterdir()), [marker])

    def test_managed_operation_requires_exact_owner_and_temporary_path(self):
        from unittest.mock import patch

        from scripts.run_pytest import scratch_parent

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            payload, fallback = root / 'payload', root / 'fallback'
            payload.mkdir()
            fallback.mkdir()
            scratch = payload / 'tmp'
            scratch.mkdir()
            marker = payload / '.base-file-owner.json'
            marker.write_text(json.dumps({'id': 'resource-id', 'marker': 'owner-marker'}), encoding='utf-8')
            journal = root / 'resource.json'
            state = {'schema': 'base-file-resource/v1', 'phase': 'active', 'path': str(payload),
                     'id': 'resource-id', 'marker': 'owner-marker'}
            journal.write_text(json.dumps(state), encoding='utf-8')
            environment = {'PDLC_FILE_OPERATION_JOURNAL': str(journal),
                           'PDLC_OPERATION_DIR': str(payload), 'TMPDIR': str(scratch)}
            with patch.dict(os.environ, environment):
                self.assertEqual(scratch_parent(fallback), scratch)
                for change in ({'phase': 'closed'}, {'marker': 'foreign-marker'}):
                    journal.write_text(json.dumps({**state, **change}), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'invalid Base managed operation'):
                        scratch_parent(fallback)
                journal.write_text(json.dumps(state), encoding='utf-8')
                with patch.dict(os.environ, {'TMPDIR': str(fallback)}):
                    with self.assertRaisesRegex(ValueError, 'invalid Base managed operation'):
                        scratch_parent(fallback)
            self.assertTrue(scratch.is_dir())
            self.assertEqual(json.loads(marker.read_text(encoding='utf-8'))['marker'], 'owner-marker')

    def test_cleanup_failure_reports_the_runner_failure_and_preserves_fixtures(self):
        from unittest.mock import patch

        from scripts.run_pytest import run

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with (patch.dict(os.environ, {'PDLC_FILE_OPERATION_JOURNAL': ''}),
                  patch('scripts.run_pytest.pytest.main', return_value=0),
                  patch('scripts.run_pytest.remove_scratch', side_effect=PermissionError(13, 'fixture held'))):
                self.assertEqual(run([], root), 1)
            path, = (root / '.local/pytest-runs').glob('*/result.json')
            receipt = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(receipt['exit_code'], 1)
            self.assertEqual(receipt['pytest_exit_code'], 0)
            self.assertEqual(receipt['cleanup'], 'recovery_required')
            self.assertEqual(receipt['cleanup_error']['errno'], 13)
            self.assertTrue(Path(receipt['scratch']).is_dir())

    @unittest.skipUnless(os.name != 'nt', 'POSIX unlink keeps the other hardlink intact')
    def test_owned_hardlink_cleanup_preserves_external_content_and_permissions(self):
        from scripts.run_pytest import remove_scratch

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            scratch = root / 'scratch'
            scratch.mkdir()
            external = root / 'outside.txt'
            external.write_bytes(b'outside fixture')
            external.chmod(stat.S_IRUSR)
            before = external.stat().st_mode
            (scratch / 'link').hardlink_to(external)
            try:
                remove_scratch(scratch)
                self.assertFalse(scratch.exists())
                self.assertEqual(external.read_bytes(), b'outside fixture')
                self.assertEqual(external.stat().st_mode, before)
            finally:
                external.chmod(stat.S_IRUSR | stat.S_IWUSR)
