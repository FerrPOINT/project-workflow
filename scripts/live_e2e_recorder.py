"""Record an executor-driven Wizard acceptance run.

The recorder is deliberately outside the product CLI. It calls the canonical
``project-workflow step`` module, records what an external executor actually
did, and produces local evidence under an ignored directory.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "database_url",
    "dsn",
    "openai_api_key",
    "password",
    "pgpassword",
    "secret",
    "token",
}
EVIDENCE_RE = re.compile(r"^Evidence-Refs:\s*([A-Z0-9_, -]+)$", re.MULTILINE)
ACTION_ID_RE = re.compile(r"^A-\d{3,}$")
MAX_EXCERPT = 2_000


class TranscriptError(ValueError):
    """The recorded event stream violates the business-E2E contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_text(value: str) -> str:
    """Remove common credentials and personal identifiers from log text."""
    value = re.sub(r"(?i)(bearer\s+)[A-Z0-9._~+/=-]+", r"\1[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[REDACTED]", value)
    value = re.sub(r"(?i)(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", value)
    value = re.sub(
        r"(?i)\b(api[_-]?key|password|secret|token)\s*([:=])\s*([^\s,;]+)",
        r"\1\2[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)([A-Z]:[\\/]Users[\\/])[^\\/\s]+",
        lambda match: f"{match.group(1)}[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\byou\s*\([^)]+\)", "you ([REDACTED_USER])", value)
    return re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", value, flags=re.I)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact values before they reach disk."""
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {item_key: redact(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def read_events(root: Path) -> list[dict[str, Any]]:
    """Load JSONL events without changing their stored payloads."""
    transcript = root / "transcript.jsonl"
    if not transcript.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(transcript.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptError(f"Invalid JSONL at line {line_number}") from exc
        if not isinstance(event, dict):
            raise TranscriptError(f"Event at line {line_number} must be an object")
        events.append(event)
    return events


def append_event(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append one redacted event to the machine transcript."""
    root.mkdir(parents=True, exist_ok=True)
    stored = {"timestamp": _now(), **redact(event)}
    with (root / "transcript.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(stored, ensure_ascii=False) + "\n")
    return stored


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def run_wizard(task: str, report: str | None = None) -> tuple[int, dict[str, Any], str]:
    """Call the canonical JSON CLI as a real subprocess."""
    command = [sys.executable, "-m", "project_workflow.interfaces.cli", "--json", "step", "--task", task]
    if report is not None:
        command.extend(["--report", report])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TranscriptError(
            f"Wizard CLI returned non-JSON output: stdout={redact_text(result.stdout)!r}; "
            f"stderr={redact_text(result.stderr)!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise TranscriptError("Wizard CLI JSON must be an object")
    return result.returncode, payload, result.stderr


def run_history(task: str) -> tuple[int, dict[str, Any], str]:
    """Read Wizard history through the canonical CLI subprocess."""
    command = [sys.executable, "-m", "project_workflow.interfaces.cli", "--json", "history", "--task", task]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TranscriptError(
            f"Wizard history returned non-JSON output: stdout={redact_text(result.stdout)!r}; "
            f"stderr={redact_text(result.stderr)!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise TranscriptError("Wizard history JSON must be an object")
    return result.returncode, payload, result.stderr


def _last_assignment_index(events: list[dict[str, Any]]) -> int:
    for index in range(len(events) - 1, -1, -1):
        if events[index].get("type") == "ASSIGNMENT":
            return index
    raise TranscriptError("No current ASSIGNMENT")


def _next_action_id(events: list[dict[str, Any]]) -> str:
    return f"A-{sum(event.get('type') == 'ACTION' for event in events) + 1:03d}"


def _require_session_task(events: list[dict[str, Any]], task: str) -> None:
    if not events or events[0].get("type") != "SESSION":
        raise TranscriptError("Session is not initialized")
    if events[0].get("task") != task:
        raise TranscriptError("SESSION belongs to another task")


def _report_refs(report: str) -> set[str]:
    match = EVIDENCE_RE.search(report)
    if match is None:
        raise TranscriptError("Report must contain Evidence-Refs")
    refs = {item.strip() for item in match.group(1).split(",") if item.strip()}
    if not refs or any(ACTION_ID_RE.fullmatch(ref) is None for ref in refs):
        raise TranscriptError("Evidence-Refs must contain current ACTION IDs")
    return refs


def validate_open_cycle(events: list[dict[str, Any]], phase: str) -> tuple[int, list[dict[str, Any]]]:
    """Require an unfinished assignment and return its current actions."""
    assignment_index = _last_assignment_index(events)
    assignment = events[assignment_index]
    if assignment.get("phase") != phase:
        raise TranscriptError("Phase does not match the current assignment")
    tail = events[assignment_index + 1 :]
    if any(event.get("type") in {"REPORT", "EVALUATOR", "TRANSITION"} for event in tail):
        raise TranscriptError("Current assignment cycle is already submitted")
    actions = [event for event in tail if event.get("type") == "ACTION"]
    return assignment_index, actions


def _validate_action_event(
    action: dict[str, Any],
    phase: str,
    *,
    artifact_root: Path | None = None,
) -> None:
    action_id = str(action.get("id", ""))
    if action.get("phase") != phase or ACTION_ID_RE.fullmatch(action_id) is None:
        raise TranscriptError("ACTION must belong to the current phase and have a stable ID")

    command = action.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(argument, str) for argument in command)
        or not command[0]
    ):
        raise TranscriptError(f"ACTION {action_id} command must be a non-empty argument list")

    cwd = action.get("cwd")
    if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
        raise TranscriptError(f"ACTION {action_id} cwd must be an absolute path")

    exit_code = action.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise TranscriptError(f"ACTION {action_id} exit_code must be an integer")

    excerpt = action.get("output_excerpt")
    if not isinstance(excerpt, str):
        raise TranscriptError(f"ACTION {action_id} output_excerpt must be a string")

    expected_log = f"command-logs/{action_id}.log"
    command_log = action.get("command_log")
    normalized_log = command_log.replace("\\", "/") if isinstance(command_log, str) else None
    if normalized_log != expected_log:
        raise TranscriptError(f"ACTION {action_id} command_log must be {expected_log}")

    if artifact_root is None:
        return

    log_path = (artifact_root / Path(*expected_log.split("/"))).resolve()
    if not log_path.is_file():
        raise TranscriptError(f"ACTION {action_id} command log is missing: {expected_log}")
    try:
        logged_output = log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TranscriptError(f"ACTION {action_id} command log cannot be read: {expected_log}") from exc
    if excerpt != logged_output[:MAX_EXCERPT]:
        raise TranscriptError(f"ACTION {action_id} command log does not match output_excerpt")


def validate_transcript(
    events: list[dict[str, Any]],
    *,
    task: str | None = None,
    expected_cycles: int | None = None,
    artifact_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate the complete SESSION -> cycle event grammar."""
    if not events or events[0].get("type") != "SESSION":
        raise TranscriptError("Transcript must start with SESSION")
    if task is not None and events[0].get("task") != task:
        raise TranscriptError("SESSION belongs to another task")

    cycles: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    index = 1
    while index < len(events):
        assignment = events[index]
        if assignment.get("type") != "ASSIGNMENT":
            raise TranscriptError(f"Expected ASSIGNMENT at event {index + 1}")
        if task is not None and assignment.get("task") != task:
            raise TranscriptError("ASSIGNMENT belongs to another task")
        phase = assignment.get("phase")
        payload = assignment.get("payload")
        if not isinstance(phase, str) or not isinstance(payload, dict) or payload.get("phase") != phase:
            raise TranscriptError("ASSIGNMENT must preserve a matching Wizard payload")
        if not isinstance(payload.get("prompt"), str):
            raise TranscriptError("ASSIGNMENT must contain the exact prompt")
        index += 1

        actions: list[dict[str, Any]] = []
        while index < len(events) and events[index].get("type") == "ACTION":
            action = events[index]
            _validate_action_event(action, phase, artifact_root=artifact_root)
            if action["id"] in action_ids:
                raise TranscriptError(f"Duplicate ACTION ID: {action['id']}")
            action_ids.add(action["id"])
            actions.append(action)
            index += 1
        if not actions:
            raise TranscriptError(f"Phase {phase} has no ACTIONS")

        if index >= len(events) or events[index].get("type") != "REPORT":
            raise TranscriptError(f"Phase {phase} is missing REPORT")
        report = events[index]
        if report.get("phase") != phase or not isinstance(report.get("report"), str):
            raise TranscriptError("REPORT must belong to the current phase")
        text_refs = _report_refs(report["report"])
        stored_refs = report.get("evidence_refs")
        if not isinstance(stored_refs, list) or set(stored_refs) != text_refs:
            raise TranscriptError("REPORT evidence_refs must exactly match Evidence-Refs in report text")
        refs = text_refs
        current_action_ids = {action["id"] for action in actions}
        if not refs or not refs.issubset(current_action_ids):
            raise TranscriptError("REPORT evidence must reference ACTIONS from the current phase only")
        index += 1

        if index >= len(events) or events[index].get("type") != "EVALUATOR":
            raise TranscriptError(f"Phase {phase} is missing EVALUATOR")
        evaluator = events[index]
        if evaluator.get("phase") != phase or not isinstance(evaluator.get("payload"), dict):
            raise TranscriptError("EVALUATOR must preserve the Wizard JSON payload")
        index += 1

        if index >= len(events) or events[index].get("type") != "TRANSITION":
            raise TranscriptError(f"Phase {phase} is missing TRANSITION")
        transition = events[index]
        if transition.get("phase") != phase or transition.get("from_phase") != phase:
            raise TranscriptError("TRANSITION must start from the assigned phase")
        index += 1
        cycles.append(
            {
                "assignment": assignment,
                "actions": actions,
                "report": report,
                "evaluator": evaluator,
                "transition": transition,
            }
        )

    if expected_cycles is not None and len(cycles) != expected_cycles:
        raise TranscriptError(f"Expected {expected_cycles} cycles, found {len(cycles)}")
    return cycles


def render_dialog(task: str, cycles: list[dict[str, Any]]) -> str:
    """Render the exact event sequence as a readable Russian dialog."""
    lines = [f"# Реальный бизнес-E2E: {task}", ""]
    for number, cycle in enumerate(cycles, start=1):
        assignment = cycle["assignment"]
        lines.extend(
            [
                f"## Цикл {number}: фаза {assignment['phase']}",
                "",
                "### Wizard выдал задание",
                "",
                "```text",
                assignment["payload"]["prompt"],
                "```",
                "",
                "### Агент реально выполнил действия",
                "",
            ]
        )
        for action in cycle["actions"]:
            command = " ".join(action["command"])
            lines.extend(
                [
                    f"- **{action['id']}** — {action.get('summary', '')}",
                    f"  - cwd: `{action.get('cwd', '')}`",
                    f"  - command: `{command}`",
                    f"  - exit code: `{action.get('exit_code')}`",
                    f"  - result: {action['output_excerpt']}",
                ]
            )
        lines.extend(
            [
                "",
                "### Отчёт агента evaluator",
                "",
                "```text",
                cycle["report"]["report"].rstrip(),
                "```",
                "",
                "### Ответ evaluator",
                "",
                "```json",
                json.dumps(cycle["evaluator"]["payload"], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Переход",
                "",
                f"`{cycle['transition'].get('from_phase')}` -> "
                f"`{cycle['transition'].get('to_phase')}` ({cycle['transition'].get('verdict')})",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _current_source_sha(metadata: dict[str, Any]) -> str | None:
    repository = metadata.get("repository")
    if isinstance(repository, str) and repository:
        result = subprocess.run(
            ["git", "-C", repository, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    head = metadata.get("head")
    return str(head) if head is not None else None


def build_summary(task: str, events: list[dict[str, Any]], cycles: list[dict[str, Any]]) -> dict[str, Any]:
    """Build audit counters without querying or mutating Wizard state."""
    verdicts = Counter(str(cycle["evaluator"]["payload"].get("verdict")) for cycle in cycles)
    final_payload = cycles[-1]["evaluator"]["payload"] if cycles else {}
    final_status = final_payload.get("status")
    if final_status is None and final_payload.get("verdict") == "PASS" and final_payload.get("next_phase") is None:
        final_status = "done"
    metadata = events[0].get("metadata", {})
    return {
        "task": task,
        "generated_at": _now(),
        "started_from_sha": metadata.get("head"),
        "source_sha": _current_source_sha(metadata),
        "skills_content_sha": metadata.get("skills_content_sha"),
        "cycles": len(cycles),
        "actions": sum(len(cycle["actions"]) for cycle in cycles),
        "verdicts": dict(sorted(verdicts.items())),
        "successful_transitions": sum(
            cycle["transition"].get("verdict") == "PASS" for cycle in cycles
        ),
        "final_phase": final_payload.get("current_phase", final_payload.get("phase")),
        "final_status": final_status,
    }


def sanitize_artifacts(root: Path) -> list[dict[str, Any]]:
    """Redact an existing transcript and command logs, including bootstrap events."""
    events = read_events(root)
    safe_events = redact(events)
    with (root / "transcript.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for event in safe_events:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    log_dir = root / "command-logs"
    if log_dir.exists():
        for log_path in log_dir.glob("*.log"):
            log_path.write_text(redact_text(log_path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    return safe_events


def finalize(root: Path, task: str, expected_cycles: int | None = None) -> dict[str, Any]:
    """Validate a completed transcript and produce human/machine summaries."""
    events = read_events(root)
    validate_transcript(events, task=task, expected_cycles=expected_cycles, artifact_root=root)
    safe_events = sanitize_artifacts(root)
    safe_cycles = validate_transcript(
        safe_events,
        task=task,
        expected_cycles=expected_cycles,
        artifact_root=root,
    )
    dialog = render_dialog(task, safe_cycles)
    summary = build_summary(task, safe_events, safe_cycles)
    (root / "dialog.md").write_text(dialog, encoding="utf-8", newline="\n")
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return summary


def command_init(args: argparse.Namespace) -> None:
    root = Path(args.root)
    if read_events(root):
        _fail("Transcript already exists")
    try:
        metadata = json.loads(args.metadata)
    except json.JSONDecodeError as exc:
        raise SystemExit("--metadata must be a JSON object") from exc
    if not isinstance(metadata, dict):
        _fail("--metadata must be a JSON object")
    code, history, stderr = run_history(args.task)
    if code != 0 or not history.get("ok"):
        _fail(f"History check failed: rc={code}; payload={redact(history)}; stderr={redact_text(stderr)}")
    if history.get("count") != 0:
        _fail("Live acceptance requires a fresh task without previous SupervisorRun records")
    event = append_event(root, {"type": "SESSION", "task": args.task, "metadata": metadata})
    print(json.dumps(event, ensure_ascii=False))


def command_assignment(args: argparse.Namespace) -> None:
    root = Path(args.root)
    events = read_events(root)
    _require_session_task(events, args.task)
    if events[-1].get("type") not in {"SESSION", "TRANSITION"}:
        _fail("Previous cycle is incomplete")
    code, payload, stderr = run_wizard(args.task)
    if code != 0 or not payload.get("ok"):
        _fail(f"Assignment failed: rc={code}; payload={redact(payload)}; stderr={redact_text(stderr)}")
    append_event(
        root,
        {"type": "ASSIGNMENT", "task": args.task, "phase": payload.get("phase"), "payload": payload},
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_action(args: argparse.Namespace) -> None:
    root = Path(args.root)
    events = read_events(root)
    _require_session_task(events, args.task)
    validate_open_cycle(events, args.phase)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        _fail("ACTION requires a command after --")

    try:
        result = subprocess.run(
            command,
            cwd=args.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            check=False,
        )
        exit_code = result.returncode
        output = result.stdout + (("\n" if result.stdout and result.stderr else "") + result.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        exit_code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
        output = str(exc)

    action_id = _next_action_id(events)
    safe_output = redact_text(output)
    log_dir = root / "command-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{action_id}.log"
    log_path.write_text(safe_output, encoding="utf-8", newline="\n")
    event = append_event(
        root,
        {
            "type": "ACTION",
            "id": action_id,
            "phase": args.phase,
            "summary": args.summary,
            "cwd": str(Path(args.cwd).resolve()),
            "command": command,
            "exit_code": exit_code,
            "output_excerpt": safe_output[:MAX_EXCERPT],
            "command_log": str(log_path.relative_to(root)),
        },
    )
    print(json.dumps(event, ensure_ascii=False))
    if exit_code != 0:
        raise SystemExit(exit_code)


def command_submit(args: argparse.Namespace) -> None:
    root = Path(args.root)
    events = read_events(root)
    _require_session_task(events, args.task)
    _, actions = validate_open_cycle(events, args.phase)
    if not actions:
        _fail("At least one ACTION is required before REPORT")
    report = Path(args.report_file).read_text(encoding="utf-8")
    refs = _report_refs(report)
    current_action_ids = {str(action["id"]) for action in actions}
    if not refs.issubset(current_action_ids):
        _fail(
            "Evidence refs must belong to current phase actions: "
            f"refs={sorted(refs)}, actions={sorted(current_action_ids)}"
        )

    append_event(root, {"type": "REPORT", "phase": args.phase, "report": report, "evidence_refs": sorted(refs)})
    code, payload, stderr = run_wizard(args.task, report)
    append_event(
        root,
        {"type": "EVALUATOR", "phase": args.phase, "exit_code": code, "payload": payload, "stderr": stderr},
    )
    append_event(
        root,
        {
            "type": "TRANSITION",
            "phase": args.phase,
            "verdict": payload.get("verdict"),
            "from_phase": payload.get("phase"),
            "to_phase": payload.get("next_phase"),
        },
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if code != 0 or payload.get("verdict") != "PASS":
        raise SystemExit(code or 2)


def command_finalize(args: argparse.Namespace) -> None:
    summary = finalize(Path(args.root), args.task, args.expected_cycles)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Exact session directory containing transcript.jsonl")
    parser.add_argument("--task", required=True)
    commands = parser.add_subparsers(dest="operation", required=True)

    init = commands.add_parser("init")
    init.add_argument("--metadata", default="{}")
    init.set_defaults(handler=command_init)

    assignment = commands.add_parser("assignment")
    assignment.set_defaults(handler=command_assignment)

    action = commands.add_parser("action")
    action.add_argument("--phase", required=True)
    action.add_argument("--summary", required=True)
    action.add_argument("--cwd", required=True)
    action.add_argument("--timeout", type=int, default=300)
    action.add_argument("command", nargs=argparse.REMAINDER)
    action.set_defaults(handler=command_action)

    submit = commands.add_parser("submit")
    submit.add_argument("--phase", required=True)
    submit.add_argument("--report-file", required=True)
    submit.set_defaults(handler=command_submit)

    finish = commands.add_parser("finalize")
    finish.add_argument("--expected-cycles", type=int)
    finish.set_defaults(handler=command_finalize)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except TranscriptError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
