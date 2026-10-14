"""Build the installable Workflow-only profile, without activating live routing."""

import argparse
import json

from project_workflow.infrastructure.single_task_delivery_instructions import (
    FIRST_STEP,
    PM_CONFIRMATION_CHECKS,
    PM_CONFIRMATION_EVIDENCE,
    PM_CONFIRMATION_INSTRUCTIONS,
    PM_PHASE_REPORT,
    PM_PUBLISH_INSTRUCTION,
    context_instruction,
    terminal_instruction,
)
from scripts.prepare_single_task_profile_proposal import ROOT, digest, encoded
from scripts.prepare_single_task_profile_proposal import render as render_proposal

CATALOG_PATH = "project_workflow/references/single_task_catalog_v1.json"
MANIFEST_PATH = "project_workflow/references/single_task_manifest_v1.json"
OVERLAY_PATH = "project_workflow/infrastructure/single_task_delivery_instructions.py"


def render() -> tuple[bytes, bytes]:
    catalog_bytes, manifest_bytes = render_proposal()
    catalog, manifest = json.loads(catalog_bytes), json.loads(manifest_bytes)
    overlay = {"path": OVERLAY_PATH, "sha256": digest((ROOT / OVERLAY_PATH).read_bytes().replace(b"\r\n", b"\n"))}
    catalog["instruction_overlay"] = manifest["instruction_overlay"] = overlay
    for workflow in catalog["workflows"]:
        role = workflow["role_key"]
        for mode in workflow["modes"]:
            mode["phases"][0]["instructions"][0]["description"] = FIRST_STEP
            mode["phases"][0]["instructions"][1]["description"] = context_instruction(role)
            mode["phases"][-1]["instructions"][-1]["description"] = terminal_instruction(role)
            if role == "project_manager":
                for phase in mode["phases"][:2]:
                    phase["instructions"][-1]["description"] = PM_PHASE_REPORT
                mode["phases"][1]["instructions"][3]["description"] = PM_PUBLISH_INSTRUCTION
                mode["phases"][1]["instructions"][4]["description"] = (
                    "Prepare the FULL saved requirements document and its exact revision/content_hash for "
                    "owner review in phase 3. Include scope, acceptance criteria, choices/tradeoffs and open "
                    "issues. This preparation is not consent and does not complete the PM execution."
                )
                phase = mode["phases"][-1]
                phase.update(
                    name="Owner confirmation before final Workflow report",
                    description="single-task-v1: project_manager/draft; confirmation within the same execution.",
                    instructions=[
                        {"description": text, "skills": ["project-workflow-executor", "tracker-operator"]}
                        for text in [*PM_CONFIRMATION_INSTRUCTIONS, terminal_instruction(role)]
                    ],
                    checks=list(PM_CONFIRMATION_CHECKS), evidence=list(PM_CONFIRMATION_EVIDENCE),
                )
            if role == "analyst":
                mode["phases"][1]["instructions"][2]["description"] = (
                    "Produce the analysis report and requirement/criterion/verification coverage matrix for this "
                    "task=root. Freeze architecture input references without creating more tasks. Prepare "
                    "result.role=analyst with a real analysis ArtifactReceipt for the existing delivery proposal; "
                    "do not borrow scheduler credentials or use scheduler Analysis submit as the agent producer."
                )
        manifest["roles"][role]["role_instructions_sha256"] = digest(encoded(workflow["modes"], canonical=True))
    catalog_bytes = encoded(catalog)
    manifest["proposal"] = False
    manifest["workflow_catalog"].update(artifact=CATALOG_PATH, sha256=digest(catalog_bytes))
    return catalog_bytes, encoded(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in zip((CATALOG_PATH, MANIFEST_PATH), render(), strict=True):
        if args.check:
            if (ROOT / path).read_bytes() != content:
                raise ValueError(f"Single-task profile differs from its inputs: {path}")
        else:
            (ROOT / path).write_bytes(content)
        print(f"{digest(content)}  {path}")
    print("Workflow installation only; Tracker routing/API and live execution remain pending parent")


if __name__ == "__main__":
    main()
