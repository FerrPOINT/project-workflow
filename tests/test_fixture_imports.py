"""Pure collection/setup must not import or prepare integration dependencies."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PROBE = r'''
import importlib.abc,runpy,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
class ApplicationImport(AssertionError):pass
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='project_workflow' or fullname.startswith('project_workflow.'):
   raise ApplicationImport('Integration dependency imported: '+fullname)
sys.meta_path.insert(0,Guard())
namespace=runpy.run_path(str(root/'tests/conftest.py'))
class FixtureRequested(Exception):pass
class Node:
 def get_closest_marker(self,name):
  return object() if name==sys.argv[2] else None
class Request:
 node=Node()
 def getfixturevalue(self,name):raise FixtureRequested(name)
mode=sys.argv[2]
if mode=='unit':
 iterator=namespace['isolate_ui_runtime_state'].__wrapped__(Request())
 assert next(iterator) is None
 try:next(iterator)
 except StopIteration:pass
 else:raise AssertionError('Unit fixture did not finish')
elif mode=='integration':
 try:next(namespace['isolate_ui_runtime_state'].__wrapped__(Request()))
 except FixtureRequested as error:assert str(error) in {'tmp_path','monkeypatch','ui_runtime_templates'}
 else:raise AssertionError('Integration fixture silently skipped preparation')
elif mode=='supervisor':
 try:namespace['supervisor_llm'].__wrapped__(object())
 except ApplicationImport:pass
 else:raise AssertionError('Requested LLM fixture did not load its implementation')
else:raise AssertionError(mode)
assert not any(n=='project_workflow' or n.startswith('project_workflow.') for n in sys.modules)
print('isolated fixture boundary: '+mode)
'''


@pytest.mark.parametrize('mode', ['unit', 'integration', 'supervisor'])
def test_fixture_dependencies_are_requested_only_by_their_consumer(mode: str) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', _PROBE, str(root), mode],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'isolated fixture boundary: {mode}' in result.stdout


def test_unit_setup_does_not_prepare_integration_fixtures(request: pytest.FixtureRequest) -> None:
    assert not {'tmp_path', 'monkeypatch', 'ui_runtime_templates'} & set(request.fixturenames)
