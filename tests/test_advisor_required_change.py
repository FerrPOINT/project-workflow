"""CP3 enforces required-change structure without correcting evaluator semantics."""

import copy
import json

import pytest

from project_workflow.infrastructure.llm import OpenAICompatibleClient, ResponseParser

pytestmark = pytest.mark.unit

ITEMS = [("first:check:17", "The result is supplied."),
         ("second:evidence:17", "The source account is supplied.")]
ALIASES = {"C1": ITEMS[0][0], "E1": ITEMS[1][0]}
CANONICAL_FIELDS = {"verdict", "covered", "missing", "blockers", "message", "confidence"}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """Pure parser tests do not initialize a runtime database or model client."""


def wire(verdict="PARTIAL", *, missing=("C1",), blockers=()):
    return {"verdict": verdict, "assessments": {
        label: {"covered": label not in missing, "reason": f"Reported facts for {label}",
                "required_change": f"Supply the required material for {label}" if label in missing else None}
        for label in ALIASES}, "blockers": list(blockers), "confidence": 0.9}


def parse(raw):
    return ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)


@pytest.mark.parametrize("covered", [False, True])
@pytest.mark.parametrize("field", ["covered", "reason", "required_change"])
def test_every_assessment_field_is_mandatory(covered, field):
    raw = wire("PASS" if covered else "PARTIAL", missing=() if covered else ("C1",))
    del raw["assessments"]["C1"][field]
    with pytest.raises(ValueError):
        parse(raw)


@pytest.mark.parametrize("covered", [False, True])
@pytest.mark.parametrize("value", [0, 1.5, False, True, [], {}, ["Change"]])
def test_required_change_types_are_strict(covered, value):
    raw = wire("PASS" if covered else "PARTIAL", missing=() if covered else ("C1",))
    raw["assessments"]["C1"]["required_change"] = value
    with pytest.raises(ValueError):
        parse(raw)


@pytest.mark.parametrize("value", [None, "", " ", "\n\t\r"])
def test_false_requires_a_nonblank_string_without_filling_it(value):
    raw = wire()
    raw["assessments"]["C1"]["required_change"] = value
    before = copy.deepcopy(raw)
    with pytest.raises(ValueError, match="Uncovered assessment requires nonblank required_change"):
        parse(raw)
    assert raw == before


@pytest.mark.parametrize("value", ["", " ", "Not applicable", "Supply material"])
def test_true_requires_exactly_null(value):
    raw = wire("PASS", missing=())
    raw["assessments"]["C1"]["required_change"] = value
    with pytest.raises(ValueError, match="Covered assessment requires null required_change"):
        parse(raw)


@pytest.mark.parametrize("verdict,missing,blockers", [
    ("PASS", (), ()),
    ("PARTIAL", ("C1",), ()),
    ("BLOCKED", ("E1",), ("Required source unavailable",)),
    ("BLOCKED", (), ("Required dependency unavailable",)),
    ("DELEGATE", ("C1",), ()),
])
def test_projection_preserves_assessments_and_the_canonical_six_fields(verdict, missing, blockers):
    raw = wire(verdict, missing=missing, blockers=blockers)
    before = copy.deepcopy(raw)
    result = parse(raw)
    assert raw == before
    assert result.assessments == {item_id: raw["assessments"][label] for label, item_id in ALIASES.items()}
    assert result.covered == [item_id for label, item_id in ALIASES.items() if label not in missing]
    assert result.missing == [item_id for label, item_id in ALIASES.items() if label in missing]
    assert set(result.raw) == CANONICAL_FIELDS
    assert result.verdict == result.raw["verdict"] == verdict
    assert result.blockers == list(blockers)
    assert result.next_phase is result.next_phase_name is None
    assert ResponseParser.parse(result.raw, required_item_ids=list(ALIASES.values())).raw == result.raw
    for label in missing:
        assert raw["assessments"][label]["reason"] in result.message
        assert raw["assessments"][label]["required_change"] in result.message
    assert all(item_id not in result.message for item_id in ALIASES.values())


def test_canonical_message_pairs_reason_and_change_in_contract_order():
    raw = wire(missing=("C1", "E1"))
    raw["assessments"] = dict(reversed(list(raw["assessments"].items())))
    result = parse(raw)
    assert result.message == (
        f"{ITEMS[0][1]}: Reported facts for C1\n"
        "\u0422\u0440\u0435\u0431\u0443\u0435\u043c\u043e\u0435 "
        "\u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435: "
        "Supply the required material for C1\n"
        f"{ITEMS[1][1]}: Reported facts for E1\n"
        "\u0422\u0440\u0435\u0431\u0443\u0435\u043c\u043e\u0435 "
        "\u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435: "
        "Supply the required material for E1"
    )


def test_nonblank_required_change_is_retained_verbatim_and_only_display_spacing_is_trimmed():
    raw = wire()
    value = "  Preserve this exact assessment value.\n "
    raw["assessments"]["C1"]["required_change"] = value
    result = parse(raw)
    assert result.assessments[ITEMS[0][0]]["required_change"] == value
    assert value.strip() in result.message and result.message == result.message.strip()


def test_semantic_disagreement_is_not_repaired_by_the_parser():
    raw = wire()
    raw["assessments"]["C1"].update(reason="All material is already present", required_change="Do nothing")
    result = parse(raw)
    assert result.verdict == "PARTIAL" and result.missing == [ITEMS[0][0]]
    assert result.assessments[ITEMS[0][0]] == raw["assessments"]["C1"]


@pytest.mark.parametrize("verdict,missing,blockers", [
    ("PASS", ("C1",), ()),
    ("PASS", (), ("Obstacle",)),
    ("PARTIAL", (), ()),
    ("PARTIAL", ("C1",), ("Obstacle",)),
    ("BLOCKED", ("C1",), ()),
    ("DELEGATE", (), ()),
    ("DELEGATE", ("C1",), ("Obstacle",)),
    ("UNKNOWN", ("C1",), ()),
])
def test_verdict_consistency_remains_strict(verdict, missing, blockers):
    with pytest.raises(ValueError):
        parse(wire(verdict, missing=missing, blockers=blockers))


@pytest.mark.parametrize("mutation", ["extra-label", "missing-label", "extra-item-field", "extra-top-field"])
def test_extra_fields_and_inexact_labels_are_refused(mutation):
    raw = wire()
    if mutation == "extra-label":
        raw["assessments"]["C999"] = copy.deepcopy(raw["assessments"]["C1"])
    elif mutation == "missing-label":
        del raw["assessments"]["E1"]
    elif mutation == "extra-item-field":
        raw["assessments"]["C1"]["next_phase"] = "Other phase"
    else:
        raw["required_change"] = "Not a top-level field"
    with pytest.raises(ValueError):
        parse(raw)


@pytest.mark.parametrize("field", ["covered", "reason", "required_change", "C1", "assessments"])
def test_raw_parser_rejects_duplicate_keys_before_projection(field):
    raw = wire()
    encoded = json.dumps(raw)
    value = raw["assessments"]["C1"].get(field, raw["assessments"].get(field, raw.get(field)))
    entry = json.dumps(field) + ": " + json.dumps(value)
    assert entry in encoded
    encoded = encoded.replace(entry, entry + ", " + entry, 1)
    with pytest.raises(ValueError, match="duplicate object keys"):
        OpenAICompatibleClient._extract_json(encoded)


def test_raw_wire_roundtrip_keeps_required_change_and_null():
    raw = wire()
    result = parse(OpenAICompatibleClient._extract_json(json.dumps(raw)))
    assert result.assessments[ITEMS[0][0]]["required_change"] == raw["assessments"]["C1"]["required_change"]
    assert result.assessments[ITEMS[1][0]]["required_change"] is None
