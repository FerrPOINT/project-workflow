"""Render the current PM publication: python -m docs.evidence.pm_structured_workflow_20261103.

Outputs a portable publication on stdout; does not publish or rewrite its historical input.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from project_workflow.domain.phase_report import PHASE_REPORT_INSTRUCTIONS


def render() -> dict:
    source = Path(__file__).with_name("pm-business-workflow-20261102.json")
    publication = json.loads(source.read_text(encoding="utf-8"))
    first, preparation, final = publication["modes"][0]["phases"]
    reporting = first["instructions"][-1]
    reporting["description"] = reporting["description"].replace(
        "Submit text on stdin", "Submit structured phase report JSON on stdin",
    )
    reporting = preparation["instructions"][-1]
    reporting["description"] = reporting["description"].replace(
        "Report completed preparation using the existing step submission procedure.",
        "Report completed preparation in the structured phase report using the existing step submission procedure.",
    )
    reporting = final["instructions"][-2]
    reporting["description"] = reporting["description"].replace(
        "submit one business-only report", "submit one structured business-only phase report",
    ).replace("with business text on stdin", "with structured phase report JSON on stdin")
    return publication


def render_skill() -> str:
    historical = Path(__file__).with_name("pm-project-workflow-skill-20261103.md").read_text(encoding="utf-8")
    header = historical.split("## Reports and stdin", 1)[0]
    return header + "## Reports and stdin\n\n" + PHASE_REPORT_INSTRUCTIONS + (
        "\n\nFollow the current phase criteria. Report actual work and include complete documents when required. "
        "A supplement may refer to unchanged previous assessments, but those marks do not supply unseen facts "
        "or a missing required document. Read the concrete reason for PARTIAL and address it. "
        "After an unknown response retain the exact operation key, version and body and read its saved outcome "
        "before retrying. Keep the installed authorization environment unchanged.\n"
    )


if __name__ == "__main__":
    print(render_skill() if sys.argv[1:] == ["--skill"] else json.dumps(render(), ensure_ascii=False, indent=2))
