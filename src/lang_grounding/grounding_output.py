"""Output side of grounding: response schema and validator (D-004, D-013, D-014).

Pure Python (standard library plus pydantic). No ROS imports, no LLM calls.

    vocabulary = load_vocabulary()                       # configs/vocabulary.json, or a path
    schema = build_output_schema(graph, vocabulary)      # for structured-output modes
    outcome = validate_grounding(parsed, graph, vocabulary)
    if isinstance(outcome, GroundingResult): ...         # validated, normalized
    else: ...                                            # list[str] of errors for a retry prompt
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from lang_grounding.scene_graph import SceneGraph

DEFAULT_VOCABULARY_PATH = Path(__file__).resolve().parents[2] / "configs" / "vocabulary.json"
DEFAULT_FLOOR = 0.001
SUM_TOL = 0.05
MAX_RATIONALE_LEN = 300

_SUM_SLACK = 1e-9  # so a sum of exactly 0.95 or 1.05 is not rejected by float rounding
_ALLOWED_KEYS = frozenset({"targets", "room_prior", "room_constraint", "rationale"})


class VocabularyError(ValueError):
    """Raised when a vocabulary file or list is unusable."""


class GroundingResult(BaseModel):
    """A validated grounding response. `room_prior` is normalized and floored."""

    model_config = ConfigDict(frozen=True)

    targets: list[str]
    room_prior: dict[str, float]
    room_constraint: list[str] | None
    rationale: str = ""


# --------------------------------------------------------------------------- vocabulary

def check_vocabulary(vocabulary: Sequence[str]) -> tuple[str, ...]:
    """Return the vocabulary as a tuple, or raise VocabularyError if it is unusable."""
    if isinstance(vocabulary, (str, bytes)) or not isinstance(vocabulary, Sequence):
        raise VocabularyError("vocabulary must be a list of class names")
    if not vocabulary:
        raise VocabularyError("vocabulary must not be empty")
    for item in vocabulary:
        if not isinstance(item, str) or not item.strip():
            raise VocabularyError(f"vocabulary entries must be non-empty strings, got {item!r}")
    if len(set(vocabulary)) != len(vocabulary):
        dups = sorted({v for v in vocabulary if list(vocabulary).count(v) > 1})
        raise VocabularyError(f"vocabulary has duplicate entries: {', '.join(dups)}")
    return tuple(vocabulary)


def load_vocabulary(path: str | Path | None = None) -> tuple[str, ...]:
    """Load the detector vocabulary from a JSON file.

    The file is an object with a "vocabulary" list. With no `path`, configs/vocabulary.json in
    the repository is used.
    """
    p = Path(path) if path is not None else DEFAULT_VOCABULARY_PATH
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise VocabularyError(f"cannot read vocabulary file {p}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VocabularyError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or "vocabulary" not in data:
        raise VocabularyError(f'{p} must be a JSON object with a "vocabulary" list')
    return check_vocabulary(data["vocabulary"])


# --------------------------------------------------------------------------- schema

def build_output_schema(graph: SceneGraph, vocabulary: Sequence[str]) -> dict[str, Any]:
    """JSON Schema for the LLM response, with the vocabulary and room IDs as enums (D-013)."""
    vocab = list(check_vocabulary(vocabulary))
    room_ids = graph.room_ids
    return {
        "title": "GroundingResponse",
        "type": "object",
        "properties": {
            "targets": {
                "description": "Target object classes, most likely first.",
                "type": "array",
                "items": {"type": "string", "enum": vocab},
                "minItems": 1,
                "uniqueItems": True,
            },
            "room_prior": {
                "description": "Probability that the target is in each room; sums to 1.",
                "type": "object",
                "properties": {
                    rid: {"type": "number", "minimum": 0, "maximum": 1} for rid in room_ids
                },
                "required": list(room_ids),
                "additionalProperties": False,
            },
            "room_constraint": {
                "description": "null, or the rooms an explicit or relational command limits "
                               "the search to.",
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {"type": "string", "enum": list(room_ids)},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                ],
            },
            "rationale": {
                "description": "One short sentence, for logs only.",
                "type": "string",
                "maxLength": MAX_RATIONALE_LEN,
            },
        },
        "required": ["targets", "room_prior", "room_constraint"],
        "additionalProperties": False,
    }


# --------------------------------------------------------------------------- validation

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_floor_setting(floor: float, n_rooms: int) -> None:
    if not _is_number(floor) or floor < 0 or floor * n_rooms >= 1:
        raise ValueError(
            f"floor must be a number >= 0 with floor * number_of_rooms < 1; "
            f"got floor={floor!r} for {n_rooms} rooms")


def _normalize_with_floor(probs: dict[str, float], floor: float) -> dict[str, float]:
    """Normalize to sum 1, then lift every room below `floor` to exactly `floor`.

    Lifted rooms are held at `floor` and the others are rescaled so the total is 1. Rescaling can
    push another room below the floor, so this repeats until none is (at most one pass per room).
    """
    total = sum(probs.values())
    base = {rid: p / total for rid, p in probs.items()}
    if floor == 0:
        return base
    lifted: set[str] = set()
    while True:
        rest = [rid for rid in base if rid not in lifted]
        scale = (1.0 - len(lifted) * floor) / sum(base[rid] for rid in rest)
        newly = {rid for rid in rest if base[rid] * scale < floor}
        if not newly:
            break
        lifted |= newly
    return {rid: floor if rid in lifted else base[rid] * scale for rid in base}


def _check_targets(data: dict, vocab: tuple[str, ...], errors: list[str]) -> list[str]:
    if "targets" not in data:
        errors.append("targets: missing (required)")
        return []
    targets = data["targets"]
    if not isinstance(targets, list):
        errors.append(f"targets: must be a list of strings, got {type(targets).__name__}")
        return []
    if not targets:
        errors.append("targets: must not be empty")
        return []
    non_strings = [t for t in targets if not isinstance(t, str)]
    if non_strings:
        errors.append(f"targets: every item must be a string, got {non_strings!r}")
    strings = [t for t in targets if isinstance(t, str)]
    dups = sorted({t for t in strings if strings.count(t) > 1})
    if dups:
        errors.append(f"targets: duplicate entries: {', '.join(repr(d) for d in dups)}")
    unknown = [t for t in dict.fromkeys(strings) if t not in vocab]
    if unknown:
        errors.append(
            f"targets: not in the allowed vocabulary: {', '.join(repr(u) for u in unknown)}. "
            f"Allowed: {', '.join(vocab)}")
    return list(targets)


def _check_room_prior(
    data: dict, room_ids: list[str], floor: float, errors: list[str]
) -> dict[str, float]:
    if "room_prior" not in data:
        errors.append("room_prior: missing (required)")
        return {}
    prior = data["room_prior"]
    if not isinstance(prior, dict):
        errors.append(f"room_prior: must be an object mapping room ID to probability, "
                      f"got {type(prior).__name__}")
        return {}

    start = len(errors)
    missing = [rid for rid in room_ids if rid not in prior]
    if missing:
        errors.append(f"room_prior: missing room ID(s): {', '.join(missing)}. "
                      f"It needs exactly one entry for each of: {', '.join(room_ids)}")
    unknown = [k for k in prior if k not in room_ids]
    if unknown:
        errors.append(f"room_prior: unknown room ID(s): {', '.join(repr(u) for u in unknown)}. "
                      f"Valid IDs: {', '.join(room_ids)}")
    for rid in room_ids:
        if rid not in prior:
            continue
        value = prior[rid]
        if not _is_number(value):
            errors.append(f"room_prior[{rid}]: must be a number, got {value!r}")
        elif not math.isfinite(value):
            errors.append(f"room_prior[{rid}]: must be finite, got {value!r}")
        elif value < 0 or value > 1:
            errors.append(f"room_prior[{rid}]: must be between 0 and 1, got {value}")
    if len(errors) > start:
        return {}

    values = {rid: float(prior[rid]) for rid in room_ids}
    total = sum(values.values())
    if abs(total - 1.0) > SUM_TOL + _SUM_SLACK:
        errors.append(f"room_prior: probabilities sum to {total:.4f}; they must sum to 1 "
                      f"(within {SUM_TOL})")
        return {}
    return _normalize_with_floor(values, floor)


def _check_room_constraint(data: dict, room_ids: list[str], errors: list[str]) -> list[str] | None:
    if "room_constraint" not in data:
        errors.append("room_constraint: missing (required; use null for no constraint)")
        return None
    constraint = data["room_constraint"]
    if constraint is None:
        return None
    if not isinstance(constraint, list):
        errors.append(f"room_constraint: must be null or a list of room IDs, "
                      f"got {type(constraint).__name__}")
        return None
    if not constraint:
        errors.append("room_constraint: must be null or a non-empty list, got an empty list")
        return None
    non_strings = [c for c in constraint if not isinstance(c, str)]
    if non_strings:
        errors.append(f"room_constraint: every item must be a room ID string, "
                      f"got {non_strings!r}")
    strings = [c for c in constraint if isinstance(c, str)]
    unknown = [c for c in dict.fromkeys(strings) if c not in room_ids]
    if unknown:
        errors.append(f"room_constraint: unknown room ID(s): "
                      f"{', '.join(repr(u) for u in unknown)}. Valid IDs: {', '.join(room_ids)}")
    dups = sorted({c for c in strings if strings.count(c) > 1})
    if dups:
        errors.append(f"room_constraint: duplicate entries: {', '.join(repr(d) for d in dups)}")
    return list(constraint)


def _check_rationale(data: dict, errors: list[str]) -> str:
    value = data.get("rationale")
    if value is None:
        return ""
    if not isinstance(value, str):
        errors.append(f"rationale: must be a string, got {type(value).__name__}")
        return ""
    if len(value) > MAX_RATIONALE_LEN:
        errors.append(f"rationale: must be at most {MAX_RATIONALE_LEN} characters, "
                      f"got {len(value)}")
    return value


def validate_grounding(
    data: Any,
    graph: SceneGraph,
    vocabulary: Sequence[str],
    *,
    floor: float = DEFAULT_FLOOR,
) -> GroundingResult | list[str]:
    """Validate a parsed LLM response (D-014).

    Returns a GroundingResult (room_prior normalized and floored) or, if anything is wrong, a
    non-empty list of error strings written to be appended to a retry prompt. All problems found
    are reported together. A bad `vocabulary` or `floor` is a programming error and raises.
    """
    vocab = check_vocabulary(vocabulary)
    room_ids = graph.room_ids
    _check_floor_setting(floor, len(room_ids))

    if not isinstance(data, dict):
        return [f"response must be a JSON object, got {type(data).__name__}"]

    errors: list[str] = []
    extra = sorted(str(k) for k in data if k not in _ALLOWED_KEYS)
    if extra:
        errors.append(f"unexpected key(s): {', '.join(extra)}. "
                      f"Allowed keys: {', '.join(sorted(_ALLOWED_KEYS))}")

    targets = _check_targets(data, vocab, errors)
    room_prior = _check_room_prior(data, room_ids, floor, errors)
    room_constraint = _check_room_constraint(data, room_ids, errors)
    rationale = _check_rationale(data, errors)

    if errors:
        return errors
    return GroundingResult(
        targets=targets,
        room_prior=room_prior,
        room_constraint=room_constraint,
        rationale=rationale,
    )
