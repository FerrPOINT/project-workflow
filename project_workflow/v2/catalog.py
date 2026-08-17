"""Loading and structural validation for the immutable v2 catalog."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "references" / "agentic_sdlc_v2.json"
class CatalogError(ValueError):
    """The catalog is internally inconsistent or has been modified in place."""


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class WorkflowCatalogV2:
    payload: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> WorkflowCatalogV2:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        catalog = cls(payload)
        catalog.validate()
        return catalog

    @property
    def revision(self) -> str:
        return str(self.payload["catalogRevision"])

    @property
    def workflow_version(self) -> str:
        return str(self.payload["workflowVersion"])

    @property
    def phases(self) -> dict[str, dict[str, Any]]:
        return {phase["phaseId"]: phase for phase in self.payload["phases"]}

    def path(self, profile: str) -> list[str]:
        try:
            return list(self.payload["profiles"][profile])
        except KeyError as exc:
            raise CatalogError(f"unknown profile: {profile}") from exc

    def phase(self, phase_id: str) -> dict[str, Any]:
        try:
            return self.phases[phase_id]
        except KeyError as exc:
            raise CatalogError(f"unknown phase: {phase_id}") from exc

    def next_phase(self, profile: str, phase_id: str) -> str | None:
        path = self.path(profile)
        try:
            index = path.index(phase_id)
        except ValueError as exc:
            raise CatalogError(f"phase {phase_id} is not in {profile} path") from exc
        return path[index + 1] if index + 1 < len(path) else None

    def resolve_route(self, profile: str, phase_id: str, failure_class: str) -> str:
        route = self.phase(phase_id)["failureRoutes"].get(failure_class, phase_id)
        if isinstance(route, dict):
            route = route.get(profile)
        if not isinstance(route, str) or route not in self.path(profile):
            raise CatalogError(f"invalid route for {phase_id}/{failure_class}/{profile}: {route!r}")
        return route

    def phase_contract(self, profile: str, phase_id: str) -> dict[str, Any]:
        """Return the phase contract with every profile-dependent route resolved."""
        if phase_id not in self.path(profile):
            raise CatalogError(f"phase {phase_id} is not in {profile} path")
        phase = deepcopy(self.phase(phase_id))
        phase["failureRoutes"] = {
            failure_class: self.resolve_route(profile, phase_id, failure_class)
            for failure_class in phase["failureRoutes"]
        }
        schema_refs = {
            requirement["schemaRef"]
            for requirement in phase["evidenceRequirements"]
            if requirement.get("schemaRef")
        }
        policy_refs = {
            requirement["policyRef"]
            for requirement in phase["evidenceRequirements"]
            if requirement.get("policyRef")
        }
        phase["artifactSchemas"] = {
            ref: deepcopy(self.payload.get("artifactSchemas", {})[ref]) for ref in sorted(schema_refs)
        }
        phase["artifactPolicies"] = {
            ref: deepcopy(self.payload.get("artifactPolicies", {})[ref]) for ref in sorted(policy_refs)
        }
        return phase

    def validate(self) -> None:
        if self.payload.get("schemaVersion") != "workflow-template/v2":
            raise CatalogError("schemaVersion must be workflow-template/v2")
        if self.workflow_version != "agentic-sdlc-v2":
            raise CatalogError("workflowVersion must be agentic-sdlc-v2")
        expected = self.revision
        unhashed = dict(self.payload)
        unhashed["catalogRevision"] = ""
        actual = hashlib.sha256(_canonical_bytes(unhashed)).hexdigest()
        if expected != actual:
            raise CatalogError("catalog checksum mismatch")
        phases = self.payload.get("phases", [])
        phase_ids = [phase.get("phaseId") for phase in phases]
        if len(phases) != 70 or len(set(phase_ids)) != 70:
            raise CatalogError("catalog must contain exactly 70 unique phases")
        expected_path_lengths = {"feature": 60, "bug": 54}
        phase_map = self.phases
        schemas = self.payload.get("artifactSchemas")
        policies = self.payload.get("artifactPolicies")
        if not isinstance(schemas, dict) or not schemas:
            raise CatalogError("artifactSchemas must be a non-empty catalog-owned mapping")
        if not isinstance(policies, dict) or not policies:
            raise CatalogError("artifactPolicies must be a non-empty catalog-owned mapping")
        for schema_ref, schema in schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise CatalogError(f"invalid artifact schema {schema_ref}: {exc.message}") from exc
        for profile, expected_length in expected_path_lengths.items():
            path = self.path(profile)
            if len(path) != expected_length or len(set(path)) != expected_length:
                raise CatalogError(f"{profile} path must contain {expected_length} unique phases")
            if any(phase_id not in phase_map for phase_id in path):
                raise CatalogError(f"{profile} path references an unknown phase")
            gates = [phase_id for phase_id in path if phase_map[phase_id].get("approvalRule")]
            if len(gates) != 5:
                raise CatalogError(f"{profile} path must contain exactly 5 human gates")
            for phase_id in path:
                for failure_class in phase_map[phase_id].get("failureRoutes", {}):
                    self.resolve_route(profile, phase_id, failure_class)
        instruction_ids: list[str] = []
        check_ids: list[str] = []
        evidence_ids: list[str] = []
        for phase in phases:
            instruction_ids.extend(item["instructionId"] for item in phase["instructions"])
            check_ids.extend(item["checkId"] for item in phase["checks"])
            evidence_ids.extend(item["requirementId"] for item in phase["evidenceRequirements"])
            for requirement in phase["evidenceRequirements"]:
                schema_ref = requirement.get("schemaRef")
                policy_ref = requirement.get("policyRef")
                if requirement["type"] == "document" and (not schema_ref or not policy_ref):
                    raise CatalogError(
                        f"document evidence {requirement['requirementId']} requires schemaRef and policyRef"
                    )
                if schema_ref and schema_ref not in schemas:
                    raise CatalogError(f"unknown schemaRef: {schema_ref}")
                if policy_ref and policy_ref not in policies:
                    raise CatalogError(f"unknown policyRef: {policy_ref}")
        for name, values, minimum in (
            ("instructions", instruction_ids, 260),
            ("checks", check_ids, 190),
            ("evidence requirements", evidence_ids, 130),
        ):
            if len(values) < minimum or len(values) != len(set(values)):
                raise CatalogError(f"{name} must be unique and contain at least {minimum} entries")


def load_default_catalog() -> WorkflowCatalogV2:
    return WorkflowCatalogV2.load(DEFAULT_CATALOG)
