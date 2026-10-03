"""Explicit business context before decomposition, alongside the legacy resource shape."""

from typing import Any

BUSINESS_PRE_DECOMPOSITION = "business-pre-decomposition"
BUSINESS_PRE_DECOMPOSITION_MODES = {"project_manager": "draft", "analyst": "analysis", "architect": "decomposition"}
LEGACY_RESOURCE_FIELDS = (
    "task_workspace_ref", "workspace_revision", "decomposition_revision_ref",
    "workspace_generation", "lease_generation",
)
PRE_DECOMPOSITION_ABSENT_FIELDS = (
    "decomposition_revision_ref", "tech_execution_workspace_ref", "tech_execution_attempt_ref",
    "workspace_generation", "lease_generation",
)


def validate_assignment_resources(
    *, assignment_shape: str | None, role_key: str, workflow_key: str, mode_key: str, execution_scope: str,
    task_workspace_ref: str | None, workspace_revision: int | None, decomposition_revision_ref: str | None,
    tech_execution_workspace_ref: str | None, tech_execution_attempt_ref: str | None,
    workspace_generation: int | None, lease_generation: int | None,
) -> None:
    resources = {
        "task_workspace_ref": task_workspace_ref, "workspace_revision": workspace_revision,
        "decomposition_revision_ref": decomposition_revision_ref, "workspace_generation": workspace_generation,
        "lease_generation": lease_generation, "tech_execution_workspace_ref": tech_execution_workspace_ref,
        "tech_execution_attempt_ref": tech_execution_attempt_ref,
    }
    if assignment_shape is None:
        if any(resources[field] is None for field in LEGACY_RESOURCE_FIELDS):
            raise ValueError("Legacy assignment requires exact decomposition/workspace refs, revisions and generations")
    elif (
        assignment_shape != BUSINESS_PRE_DECOMPOSITION or execution_scope != "business"
        or BUSINESS_PRE_DECOMPOSITION_MODES.get(role_key) != mode_key
        or workflow_key != f"hermes-sdlc:{role_key}"
    ):
        raise ValueError(
            "Business pre-decomposition requires canonical PM/draft, Analyst/analysis or Architect/decomposition"
        )
    else:
        if any(resources[field] is not None for field in PRE_DECOMPOSITION_ABSENT_FIELDS):
            raise ValueError("Business pre-decomposition cannot assert decomposition or Forge resources/generations")
        if (task_workspace_ref is None) != (workspace_revision is None):
            raise ValueError("Logical Tracker workspace ref/revision must be supplied together or both absent")
    for field in ("task_workspace_ref", "decomposition_revision_ref"):
        value = resources[field]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value.strip()) > 512):
            raise ValueError(f"{field} must be a nonblank bounded real owner ref")
    if workspace_revision is not None and (type(workspace_revision) is not int or workspace_revision <= 0):
        raise ValueError("workspace_revision must be a positive integer")
    for field in ("workspace_generation", "lease_generation"):
        value = resources[field]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{field} must be a nonnegative integer")


def assignment_resource_schema(schema: dict[str, Any]) -> None:
    """Expose the same opt-in alternatives without weakening the legacy required fields."""
    schema["oneOf"] = [
        {
            "title": "Legacy resource-bound assignment",
            "properties": {field: {"not": {"type": "null"}} for field in LEGACY_RESOURCE_FIELDS},
            "required": list(LEGACY_RESOURCE_FIELDS),
            "not": {"required": ["assignment_shape"],
                    "properties": {"assignment_shape": {"const": BUSINESS_PRE_DECOMPOSITION}}},
        },
        {
            "title": "Business-only pre-decomposition assignment",
            "required": ["assignment_shape"],
            "properties": {
                "assignment_shape": {"const": BUSINESS_PRE_DECOMPOSITION}, "execution_scope": {"const": "business"},
                **{field: {"type": "null"} for field in PRE_DECOMPOSITION_ABSENT_FIELDS},
            },
            "oneOf": [
                {"properties": {"role_key": {"const": role}, "mode_key": {"const": mode},
                                "workflow_key": {"const": f"hermes-sdlc:{role}"}}}
                for role, mode in BUSINESS_PRE_DECOMPOSITION_MODES.items()
            ],
            "allOf": [{
                "if": {"required": ["task_workspace_ref"],
                       "properties": {"task_workspace_ref": {"type": "string"}}},
                "then": {"required": ["workspace_revision"],
                         "properties": {"workspace_revision": {"type": "integer"}}},
                "else": {"properties": {"workspace_revision": {"type": "null"}}},
            }],
        },
    ]
