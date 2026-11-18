"""Tests of the ROS wrapper's plain-Python parts (D-128 to D-131). No rclpy needed.

The package lives outside src/, so it is loaded by path (the same way the house_sim tests load
the generator, D-056). Only the modules without rclpy are imported.
"""

import importlib
import importlib.util
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROS = ROOT / "ros"
PKG_DIR = ROS / "lang_grounding_ros" / "lang_grounding_ros"


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "lang_grounding_ros", PKG_DIR / "__init__.py", submodule_search_locations=[str(PKG_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["lang_grounding_ros"] = module
    spec.loader.exec_module(module)


_load_package()
mapping = importlib.import_module("lang_grounding_ros.mapping")
handler_module = importlib.import_module("lang_grounding_ros.handler")
grounder = importlib.import_module("lang_grounding_ros.grounder")

PRIOR = {"K": 0.5, "D": 0.3, "LR": 0.1, "E": 0.05, "B1": 0.03, "B2": 0.02}


def outcome(source="llm", constraint=None, latency=1.25):
    """What GroundOutcome.to_dict() returns."""
    return {
        "command": "find the banana", "source": source, "attempts": 1, "latency_s": latency,
        "model": "test-model", "errors": [], "no_keyword_match": False,
        "fallback_reason": "backend_error" if source == "fallback" else None,
        "backend_latency_s": 1.2 if source == "llm" else None,
        "result": {"targets": ["banana", "apple"], "room_prior": dict(PRIOR),
                   "room_constraint": constraint, "rationale": "kitchen first"},
    }


def make_handler(fn, timeout_s=2.0):
    return handler_module.GroundingHandler(fn, timeout_s=timeout_s)


# ----------------------------------------------------------------- mapping

def test_llm_result_maps_to_response_fields():
    fields = mapping.response_fields_from_outcome(outcome("llm"))
    assert fields == {
        "success": True, "error": "", "targets": ["banana", "apple"],
        "room_prior": list(PRIOR.items()),  # (room_id, prob) pairs, in the library's order
        "room_constraint": [],  # None means "no constraint"
        "rationale": "kitchen first", "latency_s": 1.25, "model": "test-model",
        "cache_hit": False, "source": "llm",
    }
    assert set(fields) == set(mapping.RESPONSE_FIELDS)
    assert mapping.response_fields_from_outcome(
        outcome("llm", constraint=["E", "LR"]))["room_constraint"] == ["E", "LR"]


def test_cache_and_fallback_sources():
    cached = mapping.response_fields_from_outcome(outcome("cache"))
    assert (cached["source"], cached["cache_hit"], cached["success"]) == ("cache", True, True)
    fallback = mapping.response_fields_from_outcome(outcome("fallback"))
    # a keyword-fallback result is still a usable answer; `source` tells the planner (D-130)
    assert (fallback["source"], fallback["cache_hit"], fallback["success"]) == (
        "fallback", False, True)
    assert fallback["room_prior"] and fallback["error"] == ""


# ----------------------------------------------------------------- handler: success and failures

def test_handler_success():
    handler = make_handler(lambda command: outcome("cache"))
    fields = handler.handle("find the banana")
    assert fields["success"] and fields["source"] == "cache" and fields["cache_hit"]
    handler.close()


def test_failures_return_success_false_and_never_raise():
    calls = []

    def boom(command):
        calls.append(command)
        raise ValueError("backend exploded " + "x" * 500)

    handler = make_handler(boom)
    failed = handler.handle("find the banana")
    assert failed["success"] is False and failed["source"] == "" and failed["cache_hit"] is False
    assert failed["error"].startswith("ValueError: backend exploded")
    assert len(failed["error"]) <= mapping.MAX_ERROR_LEN  # short, single line
    assert failed["targets"] == failed["room_prior"] == failed["room_constraint"] == []
    assert set(failed) == set(mapping.RESPONSE_FIELDS)

    calls.clear()
    assert handler.handle("   ")["error"] == "empty command"
    assert calls == []  # the library is not called for an empty command

    handler.close()

    bad_shape = make_handler(lambda command: {"source": "llm"})
    malformed = bad_shape.handle("find the banana")
    assert malformed["success"] is False and "bad grounding result" in malformed["error"]
    bad_shape.close()


def test_timeout_returns_promptly_with_success_false():
    release = threading.Event()
    handler = make_handler(lambda command: release.wait(5) and outcome(), timeout_s=0.1)
    start = time.monotonic()
    fields = handler.handle("find the banana")
    assert time.monotonic() - start < 2.0
    assert fields["success"] is False
    assert fields["error"] == "timed out after 0.1 s"
    assert 0.05 < fields["latency_s"] < 2.0
    release.set()
    handler.close()


def test_a_timeout_error_raised_by_the_library_is_not_reported_as_the_node_timeout():
    def fn(command):
        raise TimeoutError("upstream was slow")

    fields = make_handler(fn).handle("find the banana")
    assert fields["success"] is False
    assert fields["error"].startswith("TimeoutError: upstream was slow")


def test_a_slow_call_does_not_block_other_calls():
    release = threading.Event()

    def fn(command):
        if command == "slow":
            release.wait(5)
        return outcome()

    handler = make_handler(fn, timeout_s=5.0)
    results = {}
    slow = threading.Thread(target=lambda: results.update(slow=handler.handle("slow")))
    slow.start()
    time.sleep(0.05)  # let the slow call start
    start = time.monotonic()
    fast = handler.handle("fast")
    assert fast["success"] and time.monotonic() - start < 1.0  # answered while "slow" is waiting
    release.set()
    slow.join(timeout=5)
    assert results["slow"]["success"]
    handler.close()


# ----------------------------------------------------------------- interface files and glue

def _fields(text):
    names = []
    for line in text.splitlines():
        match = re.match(r"^\s*[\w/\[\]]+\s+(\w+)", line.split("#")[0])
        if match:
            names.append(match.group(1))
    return names


def test_interface_files_match_the_mapping_fields():
    srv = (ROS / "semantic_msgs" / "srv" / "GroundCommand.srv").read_text()
    request, response = srv.split("---")
    assert _fields(request) == ["command"]
    assert _fields(response) == list(mapping.RESPONSE_FIELDS)  # names and order
    assert _fields((ROS / "semantic_msgs" / "msg" / "RoomProb.msg").read_text()) == [
        "room_id", "prob"]
    assert _fields((ROS / "semantic_msgs" / "msg" / "Detection.msg").read_text()) == [
        "header", "label", "confidence", "position", "room_id", "source"]
    cmake = (ROS / "semantic_msgs" / "CMakeLists.txt").read_text()
    for interface in ("msg/RoomProb.msg", "msg/Detection.msg", "srv/GroundCommand.srv"):
        assert interface in cmake


def test_build_handler_with_the_fake_backend_end_to_end(tmp_path):
    setup = grounder.build_handler(
        backend="fake", env_file=str(tmp_path / "none.env"), log_dir=str(tmp_path / "logs"),
        cache_dir=tmp_path / "cache", timeout_s=5.0)
    assert setup.model == "fake-model" and setup.notes == ()
    first = setup.handler.handle("find the banana")
    assert first["success"] and first["source"] == "llm" and first["cache_hit"] is False
    assert first["targets"] == ["banana"] and first["model"] == "fake-model"
    assert len(first["room_prior"]) == 6 and first["room_constraint"] == []
    second = setup.handler.handle("find the banana")
    assert second["source"] == "cache" and second["cache_hit"] is True
    assert (tmp_path / "logs" / "grounding.jsonl").read_text().count("\n") == 2
    setup.handler.close()
