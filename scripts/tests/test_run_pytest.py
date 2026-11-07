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
