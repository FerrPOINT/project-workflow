"""Validate saved evaluator proof for current execution and historical receipts."""

import re
from typing import Any

from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser
from project_workflow.supervisor.evaluate import _fingerprint_contract_state, _report_fingerprint


def _coverage_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ) or len(value) != len(set(value)):
        raise ConflictError("Terminal evaluator IDs must be nonempty and unique")
    return value


def validate_frozen_evaluation(
    step: dict[str, Any], evaluation: dict[str, Any], *, replay_fingerprint: str | None = None,
) -> list[str]:
    contract, evaluator = evaluation.get("contract_snapshot"), evaluation.get("raw_evaluator")
    if not isinstance(contract, dict) or not isinstance(evaluator, dict):
        raise ConflictError("Terminal accepted evaluator/contract is missing")
    items = contract.get("evaluation_items")
    if not isinstance(items, list) or not items or not all(
        isinstance(item, dict) and set(item) == {"id", "text"}
        and isinstance(item["text"], str) and item["text"].strip() for item in items
    ):
        raise ConflictError("Terminal evaluator contract items are invalid")
    item_ids = _coverage_ids([item["id"] for item in items])
    covered = _coverage_ids(step.get("covered_item_ids"))
    fingerprints = [evaluation.get(key) for key in ("contract_fingerprint", "evaluated_contract_fingerprint")]
    state = evaluation.get("contract_fingerprint_state")
    if any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in fingerprints):
        raise ConflictError("Terminal frozen contract fingerprints are missing or invalid")
    if not isinstance(state, dict) or set(state) != {
        "prompt_version", "contract", "evaluation_items", "previously_covered_ids",
        "delegation_allowed", "group", "transition_routes", "phase_graph",
    }:
        raise ConflictError("Terminal frozen fingerprint inputs are missing or invalid")
    try:
        parsed = ResponseParser.parse(evaluator, required_item_ids=item_ids)
        fingerprint = _fingerprint_contract_state(state)
        report_fingerprint = (replay_fingerprint if replay_fingerprint is not None
                              else _report_fingerprint(step["task_id"], step["worker_report"], fingerprint))
    except (TypeError, ValueError):
        raise ConflictError("Terminal frozen evaluator/fingerprint proof is invalid") from None
    if (
        fingerprints != [fingerprint, fingerprint] or step.get("replay_fingerprint") != report_fingerprint
        or state["prompt_version"] != evaluation.get("prompt_version")
        or state["prompt_version"] != PromptBuilder.PROMPT_VERSION
        or state["contract"] != {key: value for key, value in contract.items() if key != "evaluation_items"}
        or state["evaluation_items"] != items
        or parsed.verdict != "PASS" or parsed.covered != covered
        or evaluation.get("covered_item_ids") != covered or set(covered) != set(item_ids)
    ):
        raise ConflictError("Terminal frozen contract/report/coverage proof mismatch")
    return covered
