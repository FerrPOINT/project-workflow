"""Build the installable Workflow-only profile, without activating live routing."""

import argparse
import json

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
