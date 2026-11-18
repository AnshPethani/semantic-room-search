"""Pure mapping from a grounding result to /ground_command response fields (D-128, D-130).

Plain Python only: no rclpy, no semantic_msgs, no lang_grounding. The input is the dict returned
by `GroundOutcome.to_dict()`; the output is a dict whose keys are exactly the response fields of
GroundCommand.srv (`RESPONSE_FIELDS`). `room_prior` is a list of (room_id, probability) pairs;
the node turns them into RoomProb messages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RESPONSE_FIELDS = (
    "success", "error", "targets", "room_prior", "room_constraint", "rationale",
    "latency_s", "model", "cache_hit", "source",
)
MAX_ERROR_LEN = 200


def map_source(source: Any) -> str:
    """The `source` response field: "cache" for a cache hit, "fallback" for the keyword
    fallback, otherwise "llm"."""
    if source == "cache":
        return "cache"
    if source == "fallback":
        return "fallback"
    return "llm"


def short_error(exc: BaseException, limit: int = MAX_ERROR_LEN) -> str:
    """One line, `ExceptionType: message`, cut to `limit` characters."""
    text = " ".join(f"{type(exc).__name__}: {exc}".split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def failure_fields(error: str, latency_s: float = 0.0) -> dict[str, Any]:
    """Response fields for a failed call: success False, a short error, everything else empty."""
    return {
        "success": False,
        "error": error,
        "targets": [],
        "room_prior": [],
        "room_constraint": [],
        "rationale": "",
        "latency_s": float(latency_s),
        "model": "",
        "cache_hit": False,
        "source": "",
    }


def response_fields_from_outcome(outcome: Mapping[str, Any]) -> dict[str, Any]:
    """Response fields for a successful call (an LLM, cached or keyword-fallback result).

    A fallback result is still a success: the planner gets a usable prior and can see from
    `source` that it did not come from the LLM (D-130). `room_constraint` None becomes an empty
    list ("no constraint").
    """
    result = outcome["result"]
    source = map_source(outcome.get("source"))
    constraint = result.get("room_constraint")
    return {
        "success": True,
        "error": "",
        "targets": [str(t) for t in result["targets"]],
        "room_prior": [(str(room), float(p)) for room, p in result["room_prior"].items()],
        "room_constraint": [] if constraint is None else [str(r) for r in constraint],
        "rationale": str(result.get("rationale") or ""),
        "latency_s": float(outcome.get("latency_s", 0.0)),
        "model": str(outcome.get("model", "")),
        "cache_hit": source == "cache",
        "source": source,
    }
