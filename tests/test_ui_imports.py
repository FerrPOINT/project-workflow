"""UI public imports remain compatible without preparing an unused app graph."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SERVICES = (
    '_build_parallel_phase_blocks', '_get_task_detail', '_load_cli_reference',
    '_load_dashboard', '_load_namespaces', '_load_phase_detail', '_load_phases',
    '_load_projects', '_load_tasks', '_load_workflows',
)
_PUBLIC = [
    'app', 'main', '_app_state', '_AppState', '_build_parallel_phase_blocks',
    '_get_task_detail', '_group_instructions', '_load_cli_reference', '_load_dashboard',
    '_load_namespaces', '_load_phase_detail', '_load_phases', '_load_projects',
    '_load_tasks', '_load_workflows', '_templates_env',
]
_ORDER_PROBE = r'''
import importlib,json,sys
sys.path.insert(0,sys.argv[1]);mode=sys.argv[2];expected=json.loads(sys.argv[3])
ui=importlib.import_module('probe_ui')
assert ui.__all__==expected
if mode=='package':
 assert set(expected)<=set(dir(ui))
 assert not any('probe_ui.'+n in sys.modules for n in ['app','main','services','templates','state','dependencies'])
 try:ui.unknown_export
 except AttributeError:pass
 else:raise AssertionError('Unknown export was accepted')
elif mode=='services-first':
 services=importlib.import_module('probe_ui.services')
 assert ui._load_tasks is services._load_tasks
 assert 'probe_ui.app' not in sys.modules and 'probe_ui.main' not in sys.modules
else:
 if mode=='app-first':importlib.import_module('probe_ui.app')
 elif mode=='main-first':importlib.import_module('probe_ui.main')
 elif mode=='legacy-first':
  from probe_ui import app,main
 elif mode!='wildcard-state':raise AssertionError(mode)
 from probe_ui import app,main
 assert app is importlib.import_module('probe_ui.app').app,'Legacy app became a module'
 assert main is importlib.import_module('probe_ui.main').main,'Legacy main became a module'
 assert ui.app is app and ui.main is main
 if mode=='wildcard-state':
  exports={};exec('from probe_ui import *',exports)
  assert set(exports)-{'__builtins__'}==set(expected)
  for name in expected:assert exports[name] is getattr(ui,name)
  state=importlib.import_module('probe_ui.state');state._app_state=object()
  assert ui._app_state is state._app_state
  dependencies=importlib.import_module('probe_ui.dependencies')
  dependencies._AppState=type('Replacement',(),{})
  assert ui._AppState is dependencies._AppState
  replacement=object();ui._app_state=replacement;assert ui._app_state is replacement
  del ui._app_state;assert ui._app_state is state._app_state
  assert ui.state is state,'Non-export submodule identity changed'
print('import order accepted: '+mode)
'''


@pytest.mark.parametrize(
    'mode', ['package', 'legacy-first', 'app-first', 'main-first', 'services-first', 'wildcard-state'],
)
def test_legacy_export_import_orders_and_live_state(tmp_path: Path, mode: str) -> None:
    package = tmp_path / 'probe_ui'
    package.mkdir()
    source = Path(__file__).resolve().parents[1] / 'project_workflow/interfaces/ui/__init__.py'
    (package / '__init__.py').write_bytes(source.read_bytes())
    # Only module binding/identity is simulated; real schemas are checked below.
    modules = {
        'app': 'class Application: pass\napp=Application()\n',
        'main': 'from .app import app\ndef main(): return app\n',
        'services': ''.join(f'def {name}(): return "{name}"\n' for name in _SERVICES),
        'templates': 'env=object()\ndef _group_instructions(): return []\n',
        'state': '_app_state=object()\n',
        'dependencies': 'class _AppState: pass\n',
    }
    for name, text in modules.items():
        (package / f'{name}.py').write_text(text, encoding='utf-8')
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', _ORDER_PROBE, str(tmp_path), mode, json.dumps(_PUBLIC)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_request_schemas_do_not_import_asgi_or_database() -> None:
    root = Path(__file__).resolve().parents[1]
    probe = r'''
import importlib.abc,sys
sys.path.insert(0,sys.argv[1])
blocked=('fastapi','uvicorn','sqlalchemy','project_workflow.infrastructure','project_workflow.interfaces.ui.app','project_workflow.interfaces.ui.routes')
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
   raise AssertionError('Unneeded application graph imported: '+fullname)
sys.meta_path.insert(0,Guard())
from project_workflow.interfaces.ui.schemas import PhaseCreate,PhaseUpdate
assert PhaseCreate(workflow_id=1,insert_after=3).phase_order==4
assert PhaseUpdate(name='Pure schema').name=='Pure schema'
assert not any(any(n==p or n.startswith(p+'.') for p in blocked) for n in sys.modules)
print('pure schemas')
'''
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', probe, str(root)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
