"""Only example order changes; evaluator rules and wire acceptance are retained."""

import ast
import hashlib
from pathlib import Path

import pytest

from project_workflow.infrastructure.llm import PromptBuilder

pytestmark = pytest.mark.unit

BASELINE_POLICY = {
    "_LlmResponse": "d7790adad7c3ccc27d2c9d9e169451dca468bcc4f9c736c119f73e89379b0ff2",
    "ResponseParser": "62ecb2324674f7f58b1d95b285929814ee10cc4a9ca7b670a08c1e197b0e616a",
}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    yield


def test_system_rules_and_response_acceptance_remain_identical_to_installed_v12():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "project_workflow/infrastructure/llm.py").read_text(encoding="utf-8"))
    actual = {
        node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in BASELINE_POLICY
    }
    assert actual == BASELINE_POLICY
    first = '  "verdict": "PASS" | "PARTIAL" | "BLOCKED" | "DELEGATE",\n'
    last = first[:-2] + "\n"
    confidence = '  "confidence": 0.0-1.0,\n'
    marker = "Output STRICT JSON with these keys:\n{\n"
    system = PromptBuilder.SYSTEM_PROMPT
    assert system.count(last) == system.count(confidence) == system.count(marker) == 1
    assert system.index('  "covered":') < system.index(last)
    restored = system.replace(last, "", 1).replace(confidence, confidence[:-2] + "\n", 1)
    restored = restored.replace(marker, marker + first, 1)
    assert hashlib.sha256(restored.encode()).hexdigest() == (
        "6ce207784c01f42fa4a08030f9f7dd0d98776d926f4c464025fe0ad15e26b058"
    )
