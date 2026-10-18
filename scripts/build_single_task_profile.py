"""Build the installable Workflow-only profile, without activating live routing."""

import argparse
import json

from project_workflow.infrastructure.single_task_delivery_instructions import (
    CRITICAL_BUSINESS_REVIEW,
    FIRST_STEP,
    PM_CONFIRMATION_CHECKS,
    PM_CONFIRMATION_EVIDENCE,
    PM_CONFIRMATION_INSTRUCTIONS,
    PM_CRITICAL_REVIEW,
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
                mode["phases"][0]["instructions"].insert(-1, {
                    "description": PM_CRITICAL_REVIEW,
                    "skills": ["project-workflow-executor", "tracker-operator"],
                })
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
            else:
                mode["phases"][1]["instructions"][-2]["description"] = CRITICAL_BUSINESS_REVIEW
                mode["phases"][-1]["instructions"][-2]["description"] = (
                    "Prepare the final report and actual role evidence. Prepare the Tracker completion comment "
                    "with work, checks, findings and the requested next stage/status. Follow the final instruction "
                    "below: actual publication/readback follows accepted Workflow evaluation, before handoff."
                )
            if role == "analyst":
                mode["phases"][1]["instructions"][2]["description"] = (
                    "Produce the analysis report and requirement/criterion/verification coverage matrix for this "
                    "task=root. Freeze architecture input references without creating more tasks. Prepare "
                    "result.role=analyst with a real analysis ArtifactReceipt for the existing delivery proposal; "
                    "do not borrow scheduler credentials or use scheduler Analysis submit as the agent producer."
                )
            final = mode["phases"][-1]
            final["instructions"].insert(-1, {
                "description": (
                    "Prepare the completion summary from actual role work, exact inputs, checks/evidence, "
                    "findings and limitations; state the permitted next stage/status as requested. "
                    "Publish the actual comment only after this final report is accepted, before handoff. "
                    "A PARTIAL/BLOCKED report still requires more work, not a frozen completion comment."
                ),
                "skills": ["project-workflow-executor", "tracker-operator"],
            })
            final["checks"].append(
                "Completion comment content and the permitted next stage/status are prepared; "
                "future effects are not prerequisites of this evaluation."
            )
            final["evidence"].append(
                "Prepared completion summary: work, exact inputs, actual checks/evidence, findings and limitations."
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
    print("Workflow profile generation only; verify installation, routing and live execution independently")


if __name__ == "__main__":
    main()
