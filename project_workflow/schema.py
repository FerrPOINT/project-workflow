"""Schema loader — reads Phase models from SQLite DB with YAML fallback.

Compatibility shim: this module remains the real implementation. New code may
also import from project_workflow.infrastructure.db.schema.
"""
from __future__ import annotations

from pathlib import Path

_SEED_PATH = Path(__file__).parent / "references" / "seed.json"
_SMOKE_SEED_PATH = Path(__file__).parent / "references" / "smoke_seed.json"

from project_workflow.infrastructure.db.schema import (  # noqa: E402
    _build_phase_from_db,
    _load_phases_seed,
    _parse_old_yaml,
    _read_seed_items,
    _read_seed_items_from_path,
    _serialize_seed_checks,
    _serialize_seed_evidence,
    _serialize_seed_instructions,
    _write_seed_document,
    ensure_phase_catalog,
    generate_progress_json,
    get_phase,
    get_phase_from_db,
    get_phase_order,
    load_phases,
    load_phases_from_db,
    persist_phase_order_to_seed,
    persist_phase_update_to_seed,
)

__all__ = [
    "_SEED_PATH",
    "_SMOKE_SEED_PATH",
    "_build_phase_from_db",
    "_load_phases_seed",
    "_parse_old_yaml",
    "_read_seed_items",
    "_read_seed_items_from_path",
    "_serialize_seed_checks",
    "_serialize_seed_evidence",
    "_serialize_seed_instructions",
    "_write_seed_document",
    "ensure_phase_catalog",
    "generate_progress_json",
    "get_phase",
    "get_phase_from_db",
    "get_phase_order",
    "load_phases",
    "load_phases_from_db",
    "persist_phase_order_to_seed",
    "persist_phase_update_to_seed",
]
