"""Historical canonical response validation stays unchanged by the private model format."""

import ast
import copy
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BASELINE_POLICY = {
    "_LlmResponse": "d7790adad7c3ccc27d2c9d9e169451dca468bcc4f9c736c119f73e89379b0ff2",
    "ResponseParser": "62ecb2324674f7f58b1d95b285929814ee10cc4a9ca7b670a08c1e197b0e616a",
}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    yield


def test_response_acceptance_is_identical_to_installed_v12():
    # Only the newly added private-to-canonical entry point is outside this
    # historical contract; the six-field model and parser retain the baseline AST.
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "project_workflow/infrastructure/llm.py").read_text(encoding="utf-8"))
    actual = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in BASELINE_POLICY:
            continue
        legacy = copy.deepcopy(node)
        if legacy.name == "ResponseParser":
            legacy.body = [member for member in legacy.body
                           if not isinstance(member, ast.FunctionDef) or member.name != "parse_assessments"]
        # The original baseline uses Python 3.14's omission of empty/None fields.
        # Normalize serializer bookkeeping only; retain all actual AST values.
        for member in ast.walk(legacy):
            member._fields = tuple(field for field, value in ast.iter_fields(member)
                                   if value != [] and not (
                                       value is None and getattr(type(member), field, ...) is None))
        actual[node.name] = hashlib.sha256(ast.dump(legacy, include_attributes=False).encode()).hexdigest()
    assert actual == BASELINE_POLICY
