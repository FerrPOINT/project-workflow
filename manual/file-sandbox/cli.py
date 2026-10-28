"""Manual acceptance recorder: invoke the installed Workflow CLI, never its engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scenario import CASES, case_id, catalog, fixture, snapshot, verify


def write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def prepare(root: Path) -> None:
    root.mkdir(exist_ok=False)
    (root / "calls").mkdir()
    for index, pair in enumerate(CASES):
        folder = root / "files" / case_id(*pair)
        folder.mkdir(parents=True)
        for name, text in fixture(index).items():
            with (folder / name).open("x", encoding="utf-8", newline="\n") as output:
                output.write(text)
    write(root / "workflows.json", catalog())
    digest = hashlib.sha256((root / "workflows.json").read_bytes()).hexdigest()
    write(root / "manifest.json", {"schema": "workflow-cli-file-sandbox/v1", "run_id": str(uuid.uuid4()),
                                    "catalog_sha256": digest,
                                    "cases": [case_id(*pair) for pair in CASES], "state": "PREPARED; NOT RUN"})


def invoke(root: Path, case: str, task: str, action: str, *, executable: str,
           report: Path | None = None, operation_key: str | None = None, version: int | None = None,
           requirements_revision: int | None = None, requirements_sha256: str | None = None,
           before_history_id: int | None = None, incomplete_probe: bool = False) -> int:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "workflow-cli-file-sandbox/v1" or case not in manifest["cases"]:
        raise ValueError("Prepare a new CLI sandbox; an engine-diagnostic database is not CLI acceptance")
    if hashlib.sha256((root / "workflows.json").read_bytes()).hexdigest() != manifest["catalog_sha256"]:
        raise ValueError("Test criteria changed after preparation; keep the original run")
    origin = urlsplit(os.environ.get("PROJECT_WORKFLOW_URL", ""))
    if (origin.scheme != "http" or origin.hostname not in {"localhost", "127.0.0.1"}
            or origin.username or origin.password or origin.query or origin.fragment):
        raise ValueError("This acceptance is local PDLC1 only; configure its actual Workflow URL")
    if report is not None and (action != "step" or not operation_key or version is None):
        raise ValueError("A report requires step, its stable operation key and the version returned by CLI")
    if incomplete_probe and report is None:
        raise ValueError("An incomplete-work probe requires an actual report submitted through CLI")
    command = [executable, "--json", action, "--task", task]
    report_text = None
    if report is not None:
        report_text = report.read_text(encoding="utf-8")
        command += ["--report", "-", "--operation-key", operation_key, "--expected-version", str(version)]
        if requirements_revision is not None:
            command += ["--requirements-revision", str(requirements_revision)]
        if requirements_sha256 is not None:
            command += ["--requirements-sha256", requirements_sha256]
    elif operation_key is not None:
        if action != "history":
            raise ValueError("Use history with the original operation key to resolve an unknown result")
        command += ["--operation-key", operation_key]
    if before_history_id is not None:
        if action != "history":
            raise ValueError("History cursor is only accepted by history")
        command += ["--before-history-id", str(before_history_id)]
    folder = root / "files" / case
    observed_before = snapshot(folder)
    started = datetime.now(timezone.utc).isoformat()
    try:
        completed = subprocess.run(command, input=report_text, text=True, encoding="utf-8", errors="strict",
                                   capture_output=True, timeout=180, shell=False)
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        unknown = False
    except subprocess.TimeoutExpired as error:
        exit_code, unknown = 124, True
        stdout = (error.stdout or b"").decode("utf-8") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = (error.stderr or b"").decode("utf-8") if isinstance(error.stderr, bytes) else error.stderr or ""
        stderr += "\nCLI timed out; resolve the original operation through history before retrying.\n"
    record = {"case": case, "task": task, "argv": command, "started_at": started,
              "finished_at": datetime.now(timezone.utc).isoformat(), "exit_code": exit_code,
              "outcome_unknown": unknown,
              "incomplete_probe": incomplete_probe,
              "origin": os.environ.get("PROJECT_WORKFLOW_URL"), "report": report_text,
              "stdout": stdout, "stderr": stderr,
              "report_sha256": hashlib.sha256(report_text.encode()).hexdigest() if report_text else None,
              "before": observed_before, "after": snapshot(folder)}
    write(root / "calls" / (uuid.uuid4().hex + ".json"), record)
    print(stdout, end="")
    print(stderr, end="", file=sys.stderr)
    return exit_code


def finish(root: Path) -> None:
    from oracle import check_calculator

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    frozen = (root / "workflows.json").read_bytes()
    if (manifest.get("schema") != "workflow-cli-file-sandbox/v1"
            or hashlib.sha256(frozen).hexdigest() != manifest["catalog_sha256"]):
        raise ValueError("Prepared CLI test criteria changed")
    prepared_catalog = json.loads(frozen)
    calls = [json.loads(path.read_text(encoding="utf-8")) for path in (root / "calls").glob("*.json")]
    calls.sort(key=lambda call: call["started_at"])
    results = []
    executions = set()
    for index, pair in enumerate(CASES):
        name = case_id(*pair)
        own = [call for call in calls if call["case"] == name]
        if not own:
            raise ValueError(f"CLI was not invoked for {name}")
        last = own[-1]
        if last["exit_code"] or "history" not in last["argv"]:
            raise ValueError(f"Finish {name} with a successful CLI history read")
        history = json.loads(last["stdout"])
        if history.get("status") != "done" or history.get("next_before") is not None:
            raise ValueError(f"CLI has not confirmed completed task and full history for {name}")
        records = history.get("records", [])
        identity = (history.get("namespace_id"), history.get("task"), history.get("execution_ref"))
        if not identity[2] or identity[2] in executions or not any(
            row["result"].get("complete") is True
            and row["result"].get("terminal_receipt", {}).get("status") == "done" for row in records
        ):
            raise ValueError(f"Unique completed CLI execution is not proven for {name}")
        executions.add(identity[2])
        writes = [call for call in own if call["report"] is not None and call["exit_code"] == 0]
        probes = [call for call in own if call.get("incomplete_probe")]
        if not probes:
            raise ValueError(f"Incomplete-work rejection through CLI was not checked for {name}")
        for call in probes:
            response = json.loads(call["stdout"])
            if (call["exit_code"] or call["before"] != call["after"]
                    or response.get("verdict") not in {"PARTIAL", "BLOCKED"}
                    or not response.get("current_phase_code")
                    or response.get("phase_code") != response["current_phase_code"]):
                raise ValueError(f"Advisor advanced or did not reject the actual incomplete report for {name}")
        for call in writes:
            response = json.loads(call["stdout"])
            if not any(row["worker_report"] == call["report"]
                       and row["result"].get("operation_key") == response.get("operation_key") for row in records):
                raise ValueError(f"CLI history does not contain the submitted operation for {name}")
        accepted = {row["result"].get("current_phase_code") for row in records
                    if row["result"].get("verdict") == "PASS"}
        workflow = next(w for w in prepared_catalog["workflows"] if w["role_key"] == pair[0])
        mode = next(mode for mode in workflow["modes"] if mode["key"] == pair[1])
        expected = {phase["code"] for phase in mode["phases"]}
        if accepted != expected or len(writes) < 3:
            raise ValueError(f"Three phase completions through CLI are not proven for {name}")
        failures = verify(root / "files" / name, index) + check_calculator(root / "files" / name)
        if failures:
            raise ValueError(f"Files fail independent checks for {name}: {failures}")
        results.append({"case": name, "task": history["task"], "namespace_id": history["namespace_id"],
                        "status": "PASS", "evaluations": len(records)})
    write(root / "result.json", {"schema": "workflow-cli-file-proof/v1", "status": "PASS", "cases": results})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "step", "history", "finish"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--case", choices=[case_id(*pair) for pair in CASES])
    parser.add_argument("--task")
    parser.add_argument("--cli", default="project-workflow")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--operation-key")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--requirements-revision", type=int)
    parser.add_argument("--requirements-sha256")
    parser.add_argument("--before-history-id", type=int)
    parser.add_argument("--incomplete-probe", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "prepare":
        prepare(root)
        print("Prepared files only; register test workflows/tasks through the normal PDLC1 APIs. NOT RUN.")
        return 0
    if args.action == "finish":
        finish(root)
        print("CLI history and independent file checks: PASS for all eight modes")
        return 0
    if not args.case or not args.task:
        parser.error("step/history require the test case and an actually assigned task key")
    executable = shutil.which(args.cli)
    if executable is None:
        parser.error("Install the normal Workflow CLI; no in-process fallback is available")
    return invoke(root, args.case, args.task, args.action, executable=executable, report=args.report,
        operation_key=args.operation_key, version=args.expected_version,
        requirements_revision=args.requirements_revision, requirements_sha256=args.requirements_sha256,
        before_history_id=args.before_history_id, incomplete_probe=args.incomplete_probe)


if __name__ == "__main__":
    raise SystemExit(main())
