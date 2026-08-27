"""Strict JSON catalog and scoped DB lookup regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.schema import (
    _load_seed,
    _phase_item_to_supervisor,
    _SeedPhase,
    ensure_phase_catalog,
    load_phases_from_db,
    load_phases_from_seed,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork

pytestmark = [pytest.mark.ui]


def _phase_by_code(uow, code: str, workflow_id: int):
    return next((phase for phase in load_phases_from_db(uow, workflow_id) if phase.code == code), None)


def _seed_path(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    dst = tmp_path / "seed.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def _bootstrapped_uow(tmp_path: Path, monkeypatch) -> SAUnitOfWork:
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'catalog.db'}")
    ensure_schema(uow.session.get_bind())
    monkeypatch.setattr(config, "SEED_PATH", _seed_path(tmp_path))
    ensure_phase_catalog(uow)
    uow.commit()
    return uow


def test_unknown_workflow_is_empty(tmp_path, monkeypatch):
    uow = _bootstrapped_uow(tmp_path, monkeypatch)
    assert load_phases_from_db(uow, workflow_id=999999) == []
    uow.close()


def test_phase_lookup_is_scoped_to_workflow(tmp_path, monkeypatch):
    uow = _bootstrapped_uow(tmp_path, monkeypatch)
    default = uow.workflows.get_default()
    assert default is not None and default.id is not None
    other_id = uow.workflows.create({"name": "Other", "is_default": 0})
    uow.phases.create(
        {"workflow_id": other_id, "code": "1.INTAKE", "name": "Other phase", "phase_order": 1}
    )
    uow.commit()

    default_phase = _phase_by_code(uow, "1.INTAKE", default.id)
    other_phase = _phase_by_code(uow, "1.INTAKE", other_id)
    assert default_phase is not None and default_phase.name != "Other phase"
    assert other_phase is not None and other_phase.name == "Other phase"
    uow.close()


@pytest.mark.parametrize(
    ("name", "contents", "message"),
    [
        ("seed.yaml", "- code: old", "должен быть в формате JSON"),
        ("malformed.json", "{", "Некорректный начальный каталог"),
        ("object.json", '{"code": "bad"}', "Корневое значение.*должно быть массивом"),
        ("items.json", '["bad"]', "нужен объект"),
        ("empty.json", "[]", "хотя бы одну фазу"),
    ],
)
def test_invalid_seed_is_rejected(tmp_path, name, contents, message):
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _load_seed(path)


def test_missing_seed_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError, match="Файл начального каталога не найден"):
        _load_seed(tmp_path / "missing.json")


def test_load_packaged_json_seed(tmp_path):
    assert load_phases_from_seed(_seed_path(tmp_path))


def test_phase_item_to_supervisor_with_delegate():
    phase = _phase_item_to_supervisor(
        _SeedPhase.model_validate({
            "phase_order": 1,
            "code": "DLG",
            "name": "Delegate",
            "delegate": {"agent": "reviewer"},
        })
    )
    assert phase.delegate is not None
    assert phase.delegate.agent == "reviewer"


def test_catalog_bootstrap_is_database_idempotent(tmp_path, monkeypatch):
    uow = _bootstrapped_uow(tmp_path, monkeypatch)
    counts = (len(uow.workflows.list()), len(uow.phases.list()), len(uow.agents.list()))
    ensure_phase_catalog(uow)
    uow.commit()
    assert counts == (len(uow.workflows.list()), len(uow.phases.list()), len(uow.agents.list()))
    uow.close()


@pytest.mark.parametrize(
    ("phase", "message"),
    [
        ({"phase_order": 1, "code": "P", "name": "Phase", "delegate": "agent"}, "delegate"),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "instructions": [{"description": "Step", "skills": "testing"}],
            },
            "skills",
        ),
        ({"phase_order": 1, "code": "P", "name": "Phase", "checks": [42]}, "checks"),
        ({"phase_order": 1, "code": "P", "name": "Phase", "evidence": [""]}, "description"),
        (
            {"phase_order": 1, "code": "P", "name": "Phase", "parallel_with": "MISSING"},
            "parallel_with",
        ),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "instructions": [{"description": "Step", "skills": None}],
            },
            "skills",
        ),
        ({"phase_order": "1", "code": "P", "name": "Phase"}, "phase_order"),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "instructions": [{"description": "Step", "example": "lost"}],
            },
            "example",
        ),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "delegate": {"agent": "reviewer", "prompt_template": "lost"},
            },
            "prompt_template",
        ),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "delegate": {"agent": "reviewer", "toolsets": []},
            },
            "toolsets",
        ),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "delegate": {"agent": "reviewer", "timeout_min": 5},
            },
            "timeout_min",
        ),
        (
            {
                "phase_order": 1,
                "code": "P",
                "name": "Phase",
                "delegate": {"agent": "reviewer", "max_cycles": 2},
            },
            "max_cycles",
        ),
    ],
)
def test_seed_rejects_invalid_nested_shapes_before_bootstrap(tmp_path, phase, message):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps([phase]), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _load_seed(path)


def test_seed_rejects_noncontiguous_order_duplicate_codes_and_descriptions(tmp_path):
    invalid_catalogs = [
        ([{"phase_order": 2, "code": "P", "name": "Phase"}], "phase_order должен быть 1"),
        (
            [
                {"phase_order": 1, "code": "P", "name": "One"},
                {"phase_order": 2, "code": "P", "name": "Two"},
            ],
            "должны быть уникальными",
        ),
        (
            [
                {
                    "phase_order": 1,
                    "code": "P",
                    "name": "Phase",
                    "checks": ["same", {"description": " SAME "}],
                }
            ],
            "повторяющиеся описания в поле checks",
        ),
    ]
    for index, (catalog, message) in enumerate(invalid_catalogs):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            _load_seed(path)


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        (
            [
                {
                    "phase_order": 1,
                    "code": "A",
                    "name": "Sync",
                    "parallel_with_phase_code": "B",
                },
                {"phase_order": 2, "code": "B", "name": "Sync"},
            ],
            "Последовательная фаза .* не может задавать parallel_with_phase_id",
        ),
        (
            [
                {
                    "phase_order": 1,
                    "code": "A",
                    "name": "Parallel",
                    "execution_type": "parallel",
                    "parallel_with_phase_code": "B",
                },
                {"phase_order": 2, "code": "B", "name": "Sync"},
            ],
            "Целевая фаза parallel_with_phase_id .* должна быть параллельной",
        ),
        (
            [
                {"phase_order": 1, "code": "A", "name": "Earlier"},
                {"phase_order": 2, "code": "B", "name": "Later"},
                {
                    "phase_order": 3,
                    "code": "C",
                    "name": "Current",
                    "rollback_target_phase_code": "B",
                },
            ],
            "rollback_target_phase_id фазы .* должен ссылаться на более раннюю фазу",
        ),
    ],
)
def test_seed_rejects_invalid_execution_graph(tmp_path, catalog, message):
    if message.startswith("rollback_target"):
        catalog[1]["rollback_target_phase_code"] = "C"
        catalog[2].pop("rollback_target_phase_code")
    path = tmp_path / "invalid-graph.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _load_seed(path)


def test_seed_accepts_isolated_parallel_phase(tmp_path):
    path = tmp_path / "isolated-parallel.json"
    path.write_text(
        json.dumps(
            [
                {
                    "phase_order": 1,
                    "code": "P",
                    "name": "Parallel",
                    "execution_type": "parallel",
                }
            ]
        ),
        encoding="utf-8",
    )

    assert _load_seed(path)[0].parallel_with_phase_code is None


def test_invalid_seed_is_detected_before_catalog_writes(tmp_path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'no-partial.db'}")
    ensure_schema(uow.session.get_bind())
    path = tmp_path / "invalid.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="хотя бы одну фазу"):
        ensure_phase_catalog(uow, path)

    assert uow.workflows.list() == []
    assert uow.phases.list() == []
    assert uow.agents.list() == []
    uow.close()


@pytest.mark.parametrize(
    "catalog",
    [
        [
            {
                "phase_order": 1,
                "code": "one",
                "name": "One",
                "delegate": {"agent": "reviewer", "hermes_profile": "profile-one"},
            },
            {
                "phase_order": 2,
                "code": "two",
                "name": "Two",
                "delegate": {"agent": "reviewer", "hermes_profile": "profile-two"},
            },
        ],
        [
            {
                "phase_order": 1,
                "code": "one",
                "name": "One",
                "delegate": {"agent": "reviewer", "hermes_profile": "shared-profile"},
            },
            {
                "phase_order": 2,
                "code": "two",
                "name": "Two",
                "delegate": {"agent": "coder", "hermes_profile": "shared-profile"},
            },
        ],
    ],
)
def test_seed_rejects_ambiguous_agent_profile_ownership_before_writes(tmp_path, catalog):
    path = tmp_path / "ambiguous-agents.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'ambiguous-agents.db'}")
    ensure_schema(uow.session.get_bind())

    with pytest.raises(ValueError, match="профил"):
        ensure_phase_catalog(uow, path)

    assert uow.workflows.list() == []
    assert uow.phases.list() == []
    assert uow.agents.list() == []
    uow.close()
