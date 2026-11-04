"""Controlled CP1 format comparison; no model request without --execute.

One journal reserves all 48 campaign slots. CP1 uses eight fixed slots; later
checkpoints remain unexecuted until their source and independent review exist.
An interrupted or finished journal is never resumed or overwritten.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, TextIO

import requests

from project_workflow.domain.phase_report import PhaseReport
from project_workflow.infrastructure.llm import OpenAICompatibleClient, ResponseParser
from project_workflow.supervisor.diagnostics import capture_attempt, text_snapshot

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs/evidence/advisor-v18-checkpoint-labels-20261104.json"
BASELINE = "09e123d76f6c97554123bc34d571c14e5d8d1046"
MAX_CALLS = 48
OUTPUT = ROOT / "docs/evidence/advisor-v18-checkpoints-20261104.json"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def baseline_system() -> str:
    source = subprocess.run(["git", "show", f"{BASELINE}:project_workflow/infrastructure/llm.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    builder = next(node for node in ast.parse(source).body
                   if isinstance(node, ast.ClassDef) and node.name == "PromptBuilder")
    values = {target.id: ast.literal_eval(node.value) for node in builder.body if isinstance(node, ast.Assign)
              for target in node.targets if isinstance(target, ast.Name)
              and target.id in {"SYSTEM_PROMPT", "PROMPT_VERSION"}}
    if values.get("PROMPT_VERSION") != "supervisor-evaluator-v17":
        raise ValueError("Unexpected baseline policy")
    return values["SYSTEM_PROMPT"]


def load_cases() -> tuple[dict, list[dict]]:
    artifact = json.loads(LABELS.read_text(encoding="utf-8"))
    cases = artifact["cp1"]
    if len(cases) != 4 or len({case["id"] for case in cases}) != 4:
        raise ValueError("CP1 requires four independent frozen cases")
    for case in cases:
        old, new = case["old_payload"], case["new_payload"]
        if {key: value for key, value in old.items() if key != "report"} != {
                key: value for key, value in new.items() if key != "report"}:
            raise ValueError("CP1 must change only report representation")
        PhaseReport.parse(json.dumps(new["report"], ensure_ascii=False, allow_nan=False))
        labels = {item["id"] for item in old["criteria"]}
        if labels != set(case["expected_assessments"]):
            raise ValueError("Frozen criterion labels differ")
    return artifact, cases


def plan(cases: list[dict]) -> list[dict]:
    slots = [{"checkpoint": "CP1", "case_id": case["id"], "variant": variant, "status": "not_run"}
             for case in cases for variant in ("old", "new")]
    slots += [{"checkpoint": "CP2", "slot": number, "status": "not_run"} for number in range(1, 5)]
    slots += [{"checkpoint": "final", "slot": number, "status": "not_run"} for number in range(1, 37)]
    assert len(slots) == MAX_CALLS
    return slots


def checkpoint(stream: TextIO, journal: dict) -> None:
    stream.seek(0)
    json.dump(journal, stream, ensure_ascii=False, allow_nan=False, indent=2)
    stream.write("\n")
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def execute(output: Path, artifact: dict, cases: list[dict]) -> dict:
    subprocess.run(["git", "diff", "--exit-code", BASELINE, "--", "project_workflow/infrastructure/llm.py"],
                   cwd=ROOT, capture_output=True, check=True)
    system = baseline_system()
    journal: dict[str, Any] = {"schema": "typed-advisor-checkpoints-v1", "baseline_source": BASELINE,
        "experiment": "CP1: report representation only", "system_policy": "supervisor-evaluator-v17",
        "candidate_policy_target": "supervisor-evaluator-v18", "max_http_calls": MAX_CALLS,
        "attempted_calls": 0, "status": "prepared", "qualified": False,
        "labels_sha256": digest(artifact), "slots": plan(cases), "manual_reason_review": "pending",
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (Path(__file__), ROOT / "project_workflow/domain/phase_report.py",
                                       ROOT / "project_workflow/infrastructure/llm.py")}}
    with output.open("x", encoding="utf-8") as stream:
        checkpoint(stream, journal)
        try:
            client = OpenAICompatibleClient()
        except Exception as exc:
            journal.update(status="preflight_error", error_type=type(exc).__name__)
            checkpoint(stream, journal)
            return journal
        expected = ("app-test", "high", 4000, 1200)
        if (client.model, client.reasoning_effort, client.max_tokens, client.timeout) != expected:
            journal["status"] = "preflight_settings_mismatch"
            checkpoint(stream, journal)
            return journal
        journal["system"] = text_snapshot(system, (client.api_key,))
        journal["settings"] = {"model": client.model, "reasoning_effort": client.reasoning_effort,
            "max_tokens": client.max_tokens, "timeout": client.timeout, "temperature": 0.1,
            "response_format": {"type": "json_object"}}
        for slot in journal["slots"][:8]:
            case = next(case for case in cases if case["id"] == slot["case_id"])
            payload = case[f"{slot['variant']}_payload"]
            user = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            items = [(item["id"], item["text"]) for item in payload["criteria"]]
            # Saved cases already use local labels; parser derives its existing C/E aliases.
            items = [(f"cp1:{'evidence' if label.startswith('E') else 'check'}:{label[1:]}", text)
                     for label, text in items]
            slot.update(status="call_started", acceptance_unknown=True, payload_sha256=digest(payload))
            journal["attempted_calls"] += 1
            journal["status"] = "running"
            checkpoint(stream, journal)
            raw, parsed, error = None, None, None
            try:
                raw = client.chat(system=system, user=user, temperature=0.1,
                                  response_format={"type": "json_object"})
                parsed = ResponseParser.parse_assessments(raw, evaluation_items=items)
                if parsed.verdict not in payload["allowed_verdicts"]:
                    raise ValueError("Disallowed verdict")
            except Exception as exc:
                error = exc
            slot["diagnostics"] = capture_attempt(client, number=1, prompt=user, raw=raw, error=error, system=system)
            slot["acceptance_unknown"] = isinstance(error, (requests.RequestException, OSError))
            if error is not None:
                slot["status"] = "technical_error"
            else:
                assert parsed is not None and isinstance(raw, dict)
                matches = (parsed.verdict == case["expected_verdict"] and parsed.blockers == case["blockers"]
                           and {label: item["covered"] for label, item in raw["assessments"].items()}
                           == {label: item["covered"] for label, item in case["expected_assessments"].items()})
                slot.update(status="matched" if matches else "classification_mismatch", matches=matches)
            stop = error is not None or slot["variant"] == "new" and slot["status"] != "matched"
            journal["status"] = "stopped_cp1" if stop else "running"
            checkpoint(stream, journal)
            if stop:
                return journal
        journal["status"] = "cp1_awaiting_independent_reason_review"
        checkpoint(stream, journal)
    return journal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.execute != (args.output is not None):
        parser.error("--execute and a new --output must be supplied together")
    if args.output is not None and args.output.resolve() != OUTPUT.resolve():
        parser.error("This campaign has one fixed journal; a new filename cannot restart its budget")
    artifact, cases = load_cases()
    if not args.execute:
        print(json.dumps({"mode": "offline", "max_http_calls": MAX_CALLS, "slots": plan(cases)}, indent=2))
        return 0
    try:
        journal = execute(args.output, artifact, cases)
    except FileExistsError:
        parser.exit(2, "Existing checkpoint evidence cannot be overwritten or resumed.\n")
    print(json.dumps({key: journal[key] for key in ("status", "attempted_calls", "qualified")}))
    return 0 if journal["status"] == "cp1_awaiting_independent_reason_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
