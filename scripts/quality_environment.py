"""Observe the current Python environment; metadata is not a reuse certificate."""
from __future__ import annotations

import hashlib
import platform
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

MAX_DISTRIBUTIONS = 512
MAX_REQUIREMENTS = 512
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OBSERVATION_BYTES = 256 * 1024


def input_hash(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(65536):
            size += len(block)
            if size > MAX_INPUT_BYTES:
                raise ValueError("Quality environment input exceeds its observation budget")
            digest.update(block)
    return digest.hexdigest()


def snapshot(root: Path) -> dict:
    """Report effective metadata and shadowed distributions without invoking uv.

    uv --with-requirements may override the project environment. Preserve the
    first distribution visible to importlib instead of overwriting it with a
    later underlay version. No installed package contents are certified here.
    """
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name

    root = Path(root)
    inputs = {name: input_hash(root / name) for name in ("pyproject.toml", "uv.lock", "constraints.txt")}
    with (root / "constraints.txt").open("rb") as stream:
        raw_requirements = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw_requirements) > MAX_INPUT_BYTES:
        raise ValueError("Quality requirements exceed their observation budget")
    requirements = raw_requirements.decode("utf-8").splitlines()
    selected: dict[str, dict] = {}
    for index, distribution in enumerate(metadata.distributions()):
        if index >= MAX_DISTRIBUTIONS:
            raise ValueError("Quality environment distribution count exceeds its observation budget")
        try:
            raw_name = distribution.metadata["Name"]
        except KeyError:
            raise ValueError("Distribution has no observable name") from None
        if not isinstance(raw_name, str) or not raw_name or len(raw_name) > 200:
            raise ValueError("Distribution has no observable name")
        name = canonicalize_name(raw_name)
        version = distribution.version
        if not isinstance(version, str) or not version or len(version) > 128:
            raise ValueError("Distribution has no observable version")
        if name not in selected:
            selected[name] = {"version": version, "shadowed_versions": []}
        else:
            selected[name]["shadowed_versions"].append(version)

    mismatches = []
    checked = 0
    parsed = 0
    for line in requirements:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if parsed >= MAX_REQUIREMENTS or len(line) > 2048:
            raise ValueError("Quality requirements exceed their observation budget")
        parsed += 1
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            raise ValueError("Overlay requirements need a supported PEP 508 observation format") from None
        if requirement.url or requirement.extras:
            raise ValueError("Direct references or requirement extras need a separate observation contract")
        if requirement.marker and not requirement.marker.evaluate():
            continue
        checked += 1
        name = canonicalize_name(requirement.name)
        observed = selected.get(name, {}).get("version")
        if observed is None or not requirement.specifier.contains(observed, prereleases=True):
            mismatches.append({"name": name, "expected": str(requirement.specifier), "observed": observed})
    if not checked:
        raise ValueError("Quality overlay requires a nonempty requirements inventory")
    if inputs != {name: input_hash(root / name) for name in inputs}:
        raise ValueError("Quality environment request changed during observation")
    return {
        "schema": "workflow-quality-environment-observation/v1",
        "status": "REQUIREMENTS_MISMATCH" if mismatches else "REQUIREMENTS_METADATA_MATCH_ONLY",
        "python": {"version": platform.python_version(), "implementation": sys.implementation.name,
                   "cache_tag": sys.implementation.cache_tag, "platform": sysconfig.get_platform(),
                   "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
                   "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"),
                   "supported_quality_version": sys.version_info[:3] == (3, 11, 15)},
        "inputs": inputs,
        "requirements_mode": "uv --with-requirements overlay; this observes the currently running interpreter",
        "requirements_checked": checked,
        "mismatches": sorted(mismatches, key=lambda row: row["name"]),
        "distributions": dict(sorted(selected.items())),
        "package_payload_verified": False,
        "interpreter_content_verified": False,
        "manager_identity_verified": False,
        "automatic_reuse_eligible": False,
        "observation_scope": (
            "One metadata enumeration; imported package contents and concurrent mutations are not certified"
        ),
        "qualification": (
            "DIAGNOSTIC_METADATA_ONLY; a matching version inventory does not certify installed contents or test results"
        ),
    }
