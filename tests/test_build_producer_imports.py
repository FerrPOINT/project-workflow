"""Image preparation imports core/catalog code without the optional UI stack."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROBE = '''
import importlib.abc,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
blocked={'fastapi','starlette','uvicorn','jinja2','httpx','httpcore','jwt',
         'cryptography','cffi','pycparser','anyio','h11','annotated_doc'}
class CoreOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in blocked:
   raise ImportError('Image producer requested optional UI dependency: '+fullname)
sys.meta_path.insert(0,CoreOnly())
from scripts import build_runtime_image as producer
from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog
from scripts.verify_base_sdlc_candidate import load_pinned_package
relative=producer.BASE_CATALOG_PATH if sys.argv[2]=='base' else producer.CATALOG_PATH
catalog=load_managed_catalog(Path(sys.argv[1])/relative)
assert catalog.catalog_version==(4 if sys.argv[2]=='base' else 2)
assert callable(producer.compatible_build_context) and callable(producer.derive_compatibility)
assert callable(load_pinned_package)
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
print(json.dumps({'variant':sys.argv[2],'catalog_version':catalog.catalog_version}))
'''


@pytest.mark.parametrize('variant', ['legacy', 'base'])
def test_producer_catalog_imports_do_not_require_optional_ui(variant, tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', _PROBE, str(root), variant],
        cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['variant'] == variant
