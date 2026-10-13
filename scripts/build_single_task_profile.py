"""Build the installable Workflow-only profile, without activating live routing."""

import argparse
import json

from project_workflow.infrastructure.single_task_delivery_instructions import FIRST_STEP, terminal_instruction
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
            mode["phases"][-1]["instructions"][-1]["description"] = terminal_instruction(role)
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
