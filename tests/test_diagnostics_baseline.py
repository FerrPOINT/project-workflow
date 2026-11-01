"""Diagnostic-only release keeps the installed fb983944 evaluation policy."""

import ast
import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BASELINE_POLICY = {
    "PromptBuilder": "9384ff888b32dd69b47f6320276bf56c1a1fc1bf62b0bea8399b22a7ae2e3c05",
    "_LlmResponse": "d7790adad7c3ccc27d2c9d9e169451dca468bcc4f9c736c119f73e89379b0ff2",
    "ResponseParser": "62ecb2324674f7f58b1d95b285929814ee10cc4a9ca7b670a08c1e197b0e616a",
}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    yield


def test_prompts_and_response_acceptance_are_identical_to_installed_v12():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "project_workflow/infrastructure/llm.py").read_text(encoding="utf-8"))
    actual = {
        node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in BASELINE_POLICY
    }
    assert actual == BASELINE_POLICY
