import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from lang_grounding.grounding_output import (
    DEFAULT_FLOOR,
    DEFAULT_VOCABULARY_PATH,
    GroundingResult,
    VocabularyError,
    build_output_schema,
    load_vocabulary,
    validate_grounding,
)
from lang_grounding.scene_graph import load_scene_graph

ROOT = Path(__file__).resolve().parents[1]
GRAPH = load_scene_graph(ROOT / "data" / "scene_graph.placeholder.json")
ROOMS = ["E", "K", "LR", "D", "B1", "B2"]
VOCAB = (
    "banana", "apple", "orange", "sandwich", "bottle", "cup",
    "bowl", "book", "laptop", "remote", "cell phone", "teddy bear",
)


@pytest.fixture
def good():
    return {
        "targets": ["banana", "apple", "sandwich"],
        "room_prior": {"K": 0.55, "D": 0.30, "LR": 0.10, "E": 0.02, "B1": 0.015, "B2": 0.015},
        "room_constraint": None,
        "rationale": "Food is most likely in the kitchen, then the dining area.",
    }


def run(data, **kwargs):
    return validate_grounding(data, GRAPH, VOCAB, **kwargs)


def errors_of(data, **kwargs):
    out = run(data, **kwargs)
    assert isinstance(out, list) and out, f"expected errors, got {out!r}"
    return out


def has_error(errors, fragment):
    return any(fragment in e for e in errors)


# ----------------------------------------------------------------- vocabulary

def test_default_vocabulary_file():
    assert DEFAULT_VOCABULARY_PATH.exists()
    assert load_vocabulary() == VOCAB


def test_vocabulary_override_path(tmp_path):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"vocabulary": ["cup", "book"]}))
    assert load_vocabulary(p) == ("cup", "book")


def test_vocabulary_override_list_is_used_by_validator(good):
    good["targets"] = ["cup"]
    assert isinstance(validate_grounding(good, GRAPH, ["cup", "book"]), GroundingResult)
    good["targets"] = ["banana"]
    out = validate_grounding(good, GRAPH, ["cup", "book"])
    assert isinstance(out, list) and has_error(out, "'banana'")


@pytest.mark.parametrize("content, message", [
    ("{not json", "not valid JSON"),
    ("[]", '"vocabulary" list'),
    ('{"other": []}', '"vocabulary" list'),
    ('{"vocabulary": []}', "must not be empty"),
    ('{"vocabulary": ["cup", "cup"]}', "duplicate"),
    ('{"vocabulary": ["cup", 3]}', "non-empty strings"),
    ('{"vocabulary": "cup"}', "list of class names"),
])
def test_bad_vocabulary_files(tmp_path, content, message):
    p = tmp_path / "v.json"
    p.write_text(content)
    with pytest.raises(VocabularyError, match=message):
        load_vocabulary(p)


def test_missing_vocabulary_file(tmp_path):
    with pytest.raises(VocabularyError, match="cannot read"):
        load_vocabulary(tmp_path / "nope.json")


def test_bad_vocabulary_argument_raises(good):
    with pytest.raises(VocabularyError):
        validate_grounding(good, GRAPH, [])


# ----------------------------------------------------------------- schema

def test_schema_enums_match_vocabulary_and_rooms():
    schema = build_output_schema(GRAPH, VOCAB)
    props = schema["properties"]
    assert props["targets"]["items"]["enum"] == list(VOCAB)
    assert list(props["room_prior"]["properties"]) == ROOMS
    assert props["room_prior"]["required"] == ROOMS
    assert props["room_prior"]["additionalProperties"] is False
    constraint_array = next(s for s in props["room_constraint"]["anyOf"] if s["type"] == "array")
    assert constraint_array["items"]["enum"] == ROOMS
    assert schema["required"] == ["targets", "room_prior", "room_constraint"]
    assert props["rationale"]["maxLength"] == 300
    json.dumps(schema)  # must be JSON-serializable


def test_schema_uses_overridden_vocabulary():
    schema = build_output_schema(GRAPH, ["cup", "book"])
    assert schema["properties"]["targets"]["items"]["enum"] == ["cup", "book"]


# ----------------------------------------------------------------- valid

def test_valid_response(good):
    out = run(good)
    assert isinstance(out, GroundingResult)
    assert out.targets == ["banana", "apple", "sandwich"]
    assert list(out.room_prior) == ROOMS  # graph order
    assert out.room_prior["K"] == pytest.approx(0.55)
    assert math.isclose(sum(out.room_prior.values()), 1.0)
    assert out.room_constraint is None
    assert out.rationale.startswith("Food")


def test_valid_with_constraint_and_no_rationale(good):
    good["room_constraint"] = ["E", "LR"]
    del good["rationale"]
    out = run(good)
    assert isinstance(out, GroundingResult)
    assert out.room_constraint == ["E", "LR"]
    assert out.rationale == ""


def test_null_rationale_accepted(good):
    good["rationale"] = None
    assert run(good).rationale == ""


def test_result_is_immutable(good):
    out = run(good)
    with pytest.raises(ValidationError):
        out.rationale = "x"


# ----------------------------------------------------------------- top level

def test_not_an_object():
    assert has_error(errors_of([]), "must be a JSON object")


def test_unexpected_key(good):
    good["confidence"] = 0.9
    assert has_error(errors_of(good), "unexpected key(s): confidence")


def test_errors_are_collected_together(good):
    good["targets"] = []
    good["room_constraint"] = ["ZZ"]
    errors = errors_of(good)
    assert has_error(errors, "targets") and has_error(errors, "room_constraint")


# ----------------------------------------------------------------- targets

def test_targets_missing(good):
    del good["targets"]
    assert has_error(errors_of(good), "targets: missing")


def test_targets_empty(good):
    good["targets"] = []
    assert has_error(errors_of(good), "targets: must not be empty")


def test_targets_not_a_list(good):
    good["targets"] = "banana"
    assert has_error(errors_of(good), "targets: must be a list")


def test_targets_duplicates(good):
    good["targets"] = ["banana", "apple", "banana"]
    assert has_error(errors_of(good), "duplicate entries: 'banana'")


def test_targets_not_in_vocabulary(good):
    good["targets"] = ["banana", "mug"]
    errors = errors_of(good)
    assert has_error(errors, "not in the allowed vocabulary: 'mug'")
    assert has_error(errors, "Allowed: banana")


def test_targets_non_string_item(good):
    good["targets"] = ["banana", 3]
    assert has_error(errors_of(good), "every item must be a string")


# ----------------------------------------------------------------- room_prior

def test_room_prior_missing(good):
    del good["room_prior"]
    assert has_error(errors_of(good), "room_prior: missing (required)")


def test_room_prior_not_an_object(good):
    good["room_prior"] = [0.5, 0.5]
    assert has_error(errors_of(good), "room_prior: must be an object")


def test_room_prior_missing_room(good):
    del good["room_prior"]["B2"]
    good["room_prior"]["K"] += 0.015
    assert has_error(errors_of(good), "missing room ID(s): B2")


def test_room_prior_unknown_room(good):
    good["room_prior"]["GARAGE"] = 0.0
    assert has_error(errors_of(good), "unknown room ID(s): 'GARAGE'")


@pytest.mark.parametrize("value, message", [
    (1.5, "must be between 0 and 1"),
    (-0.1, "must be between 0 and 1"),
    ("0.3", "must be a number"),
    (True, "must be a number"),
    (None, "must be a number"),
    (float("nan"), "must be finite"),
    (float("inf"), "must be finite"),
])
def test_room_prior_bad_value(good, value, message):
    good["room_prior"]["D"] = value
    assert has_error(errors_of(good), f"room_prior[D]: {message}")


def test_sum_too_low_rejected(good):
    good["room_prior"]["K"] = 0.35  # total 0.80
    assert has_error(errors_of(good), "sum to 0.8000")


def test_sum_slightly_high_rejected(good):
    good["room_prior"]["K"] = 0.61  # total 1.06
    assert has_error(errors_of(good), "sum to 1.0600")


def test_sum_slightly_off_is_renormalized(good):
    good["room_prior"]["K"] = 0.58  # total 1.03
    out = run(good)
    assert isinstance(out, GroundingResult)
    assert math.isclose(sum(out.room_prior.values()), 1.0)
    assert out.room_prior["K"] == pytest.approx(0.58 / 1.03)


def test_sum_slightly_low_is_renormalized(good):
    good["room_prior"]["K"] = 0.51  # total 0.96
    out = run(good)
    assert isinstance(out, GroundingResult)
    assert math.isclose(sum(out.room_prior.values()), 1.0)


# ----------------------------------------------------------------- floor

def test_floor_lifts_zero_rooms(good):
    good["room_prior"] = {"K": 0.7, "D": 0.3, "LR": 0.0, "E": 0.0, "B1": 0.0, "B2": 0.0}
    out = run(good)
    assert isinstance(out, GroundingResult)
    assert all(p >= DEFAULT_FLOOR - 1e-12 for p in out.room_prior.values())
    assert math.isclose(sum(out.room_prior.values()), 1.0)
    assert out.room_prior["LR"] == pytest.approx(DEFAULT_FLOOR)
    assert out.room_prior["K"] > out.room_prior["D"]  # order preserved


def test_floor_is_configurable(good):
    good["room_prior"] = {"K": 0.7, "D": 0.3, "LR": 0.0, "E": 0.0, "B1": 0.0, "B2": 0.0}
    out = run(good, floor=0.05)
    assert out.room_prior["E"] == pytest.approx(0.05)
    assert math.isclose(sum(out.room_prior.values()), 1.0)


def test_floor_cascade():
    # Rescaling after the first lift pushes B1 below the floor, so it must be lifted too.
    data = {
        "targets": ["cup"],
        "room_prior": {"E": 0.0, "K": 0.09, "LR": 0.5, "D": 0.3, "B1": 0.11, "B2": 0.0},
        "room_constraint": None,
    }
    out = run(data, floor=0.1)
    assert isinstance(out, GroundingResult)
    p = out.room_prior
    assert all(v >= 0.1 - 1e-12 for v in p.values())
    assert math.isclose(sum(p.values()), 1.0)
    assert p["B1"] == pytest.approx(0.1)
    assert p["LR"] == pytest.approx(0.375)
    assert p["D"] == pytest.approx(0.225)


def test_floor_zero_leaves_zeros(good):
    good["room_prior"] = {"K": 0.7, "D": 0.3, "LR": 0.0, "E": 0.0, "B1": 0.0, "B2": 0.0}
    out = run(good, floor=0.0)
    assert out.room_prior["LR"] == 0.0


def test_values_above_floor_unchanged_when_sum_is_one(good):
    out = run(good)
    for rid, p in good["room_prior"].items():
        assert out.room_prior[rid] == pytest.approx(p)


@pytest.mark.parametrize("floor", [-0.1, 0.2, "x"])
def test_bad_floor_setting_raises(good, floor):
    with pytest.raises(ValueError, match="floor"):
        run(good, floor=floor)


# ----------------------------------------------------------------- room_constraint

def test_constraint_missing(good):
    del good["room_constraint"]
    assert has_error(errors_of(good), "room_constraint: missing")


def test_constraint_empty_list(good):
    good["room_constraint"] = []
    assert has_error(errors_of(good), "non-empty list")


def test_constraint_not_a_list(good):
    good["room_constraint"] = "LR"
    assert has_error(errors_of(good), "must be null or a list")


def test_constraint_unknown_room(good):
    good["room_constraint"] = ["LR", "GARAGE"]
    assert has_error(errors_of(good), "unknown room ID(s): 'GARAGE'")


def test_constraint_duplicates(good):
    good["room_constraint"] = ["LR", "LR"]
    assert has_error(errors_of(good), "duplicate entries: 'LR'")


def test_constraint_non_string_item(good):
    good["room_constraint"] = [1]
    assert has_error(errors_of(good), "every item must be a room ID string")


# ----------------------------------------------------------------- rationale

def test_rationale_at_limit_ok(good):
    good["rationale"] = "x" * 300
    assert isinstance(run(good), GroundingResult)


def test_rationale_too_long(good):
    good["rationale"] = "x" * 301
    assert has_error(errors_of(good), "at most 300 characters")


def test_rationale_not_a_string(good):
    good["rationale"] = 5
    assert has_error(errors_of(good), "rationale: must be a string")
