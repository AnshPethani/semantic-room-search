import json
from pathlib import Path

import pytest

from lang_grounding.backends import (
    BackendError,
    BackendRateLimitError,
    BackendResponseError,
    BackendTimeoutError,
    FakeBackend,
)
from lang_grounding.cache import GroundingCache, make_cache_key, normalize_command
from lang_grounding.ground import ground, main
from lang_grounding.grounding_log import GroundingLogger
from lang_grounding.grounding_output import load_vocabulary
from lang_grounding.keyword_fallback import load_keyword_table
from lang_grounding.prompts import FewShotExample, PromptBuilder
from lang_grounding.scene_graph import load_scene_graph

ROOT = Path(__file__).resolve().parents[1]
GRAPH = load_scene_graph(ROOT / "data" / "scene_graph.placeholder.json")
VOCAB = load_vocabulary()
TABLE = load_keyword_table()
COMMAND = "find the banana"

GOOD_RESPONSE = {
    "targets": ["banana", "apple"],
    "room_prior": {"K": 0.55, "D": 0.30, "LR": 0.10, "E": 0.02, "B1": 0.015, "B2": 0.015},
    "room_constraint": None,
    "rationale": "Food is usually in the kitchen.",
}
BAD_RESPONSE = {**GOOD_RESPONSE, "targets": ["mug"]}  # not in the vocabulary
EXAMPLE = FewShotExample("example command", GOOD_RESPONSE)


def builder(template="SYS {scene_graph} | {vocabulary} | {examples}", examples=(EXAMPLE,)):
    return PromptBuilder(template, examples)


def run(script, *, command=COMMAND, cache=None, logger=None, **kwargs):
    backend = FakeBackend(script)
    outcome = ground(command, GRAPH, VOCAB, backend, cache, logger,
                     prompts=builder(), keyword_table=TABLE, **kwargs)
    return outcome, backend


# ----------------------------------------------------------------- flow

def test_valid_first_try():
    outcome, backend = run([GOOD_RESPONSE])
    assert outcome.source == "llm"
    assert outcome.attempts == 1
    assert outcome.errors == ()
    assert outcome.model == "fake-model"
    assert outcome.result.targets == ["banana", "apple"]
    assert outcome.result.room_prior["K"] == pytest.approx(0.55)
    assert len(backend.calls) == 1
    assert backend.calls[0].user_prompt == "Command: find the banana"
    assert "example command" in backend.calls[0].system_prompt


def test_retry_succeeds_with_errors_appended():
    outcome, backend = run([BAD_RESPONSE, GOOD_RESPONSE])
    assert outcome.source == "llm"
    assert outcome.attempts == 2
    assert len(backend.calls) == 2
    assert any("attempt 1" in e and "mug" in e for e in outcome.errors)
    first, second = backend.calls
    assert second.user_prompt.startswith(first.user_prompt)
    assert "mug" in second.user_prompt and "rejected" in second.user_prompt
    assert second.system_prompt == first.system_prompt


def test_retry_fails_then_fallback():
    outcome, backend = run([BAD_RESPONSE, BAD_RESPONSE])
    assert outcome.source == "fallback"
    assert outcome.attempts == 2
    assert len(backend.calls) == 2
    assert len(outcome.errors) >= 2
    assert outcome.result.targets == ["banana"]  # from the keyword table
    assert outcome.no_keyword_match is False


def test_non_json_response_is_retried():
    outcome, _ = run(["this is not json", GOOD_RESPONSE])
    assert outcome.source == "llm"
    assert any("not valid JSON" in e for e in outcome.errors)


def test_code_fenced_json_is_accepted():
    fenced = "```json\n" + json.dumps(GOOD_RESPONSE) + "\n```"
    outcome, backend = run([fenced])
    assert outcome.source == "llm" and outcome.attempts == 1 and len(backend.calls) == 1


@pytest.mark.parametrize("error", [
    BackendTimeoutError("slow"),
    BackendRateLimitError("quota"),
    BackendResponseError("garbled"),
    BackendError("down"),
])
def test_backend_error_goes_to_fallback_without_retry(error):
    outcome, backend = run([error, GOOD_RESPONSE])
    assert outcome.source == "fallback"
    assert outcome.attempts == 1
    assert len(backend.calls) == 1
    assert type(error).__name__ in outcome.errors[0]
    assert outcome.result.targets == ["banana"]


def test_fallback_without_keyword_match_is_flagged():
    outcome, _ = run([BackendError("down")], command="xyzzy plugh")
    assert outcome.source == "fallback"
    assert outcome.no_keyword_match is True
    assert outcome.result.targets == list(VOCAB)
    assert all(abs(p - 1 / 6) < 1e-9 for p in outcome.result.room_prior.values())


def test_empty_command_rejected():
    with pytest.raises(ValueError, match="empty"):
        run([GOOD_RESPONSE], command="   ")


def test_outcome_to_dict_is_json_serializable():
    outcome, _ = run([GOOD_RESPONSE])
    data = json.loads(json.dumps(outcome.to_dict()))
    assert data["source"] == "llm" and data["result"]["targets"] == ["banana", "apple"]


# ----------------------------------------------------------------- cache

def test_cache_hit_makes_no_backend_call(tmp_path):
    cache = GroundingCache(tmp_path)
    first, _ = run([GOOD_RESPONSE], cache=cache)
    assert first.source == "llm"
    second, backend = run([], cache=cache)  # an empty script would raise if called
    assert second.source == "cache"
    assert second.attempts == 0
    assert backend.calls == []
    assert second.result == first.result


def test_cache_hit_for_trivially_different_command(tmp_path):
    cache = GroundingCache(tmp_path)
    run([GOOD_RESPONSE], cache=cache)
    outcome, backend = run([], cache=cache, command="  FIND   the  Banana ")
    assert outcome.source == "cache" and backend.calls == []


def test_fallback_results_are_not_cached(tmp_path):
    cache = GroundingCache(tmp_path)
    outcome, _ = run([BAD_RESPONSE, BAD_RESPONSE], cache=cache)
    assert outcome.source == "fallback"
    assert list(tmp_path.iterdir()) == []
    outcome, _ = run([BackendTimeoutError("t")], cache=cache)
    assert outcome.source == "fallback"
    assert list(tmp_path.iterdir()) == []
    # and the next call really goes to the backend again
    again, backend = run([GOOD_RESPONSE], cache=cache)
    assert again.source == "llm" and len(backend.calls) == 1
    assert len(list(tmp_path.iterdir())) == 1


def test_corrupt_cache_file_is_a_miss(tmp_path):
    cache = GroundingCache(tmp_path)
    run([GOOD_RESPONSE], cache=cache)
    (path,) = tmp_path.iterdir()
    path.write_text("{broken")
    outcome, backend = run([GOOD_RESPONSE], cache=cache)
    assert outcome.source == "llm" and len(backend.calls) == 1


def key(**overrides):
    args = {
        "command": COMMAND, "graph": GRAPH, "vocabulary": VOCAB, "model": "m",
        "system_prompt": "prompt", "floor": 0.001,
    }
    args.update(overrides)
    return make_cache_key(**args)


def test_cache_key_is_stable_and_normalizes_the_command():
    assert key() == key()
    assert key(command="  FIND the   banana") == key()
    assert normalize_command("  A   b ") == "a b"


def test_cache_key_changes_with_each_input():
    base = key()
    assert key(system_prompt="prompt edited") != base
    assert key(model="other-model") != base
    assert key(vocabulary=list(VOCAB) + ["spoon"]) != base
    assert key(vocabulary=list(reversed(VOCAB))) != base
    assert key(command="find the apple") != base
    assert key(floor=0.01) != base
    changed = GRAPH.model_copy(deep=True)
    changed.rooms[0].name = "hallway"
    assert key(graph=changed) != base
    door_moved = GRAPH.model_copy(deep=True)
    door_moved.doors[0].between = ["K", "outside"]
    assert key(graph=door_moved) != base


def test_cache_key_ignores_viewpoints():
    with_viewpoints = GRAPH.model_copy(deep=True)
    with_viewpoints.rooms[0].viewpoints = [(1.0, 5.0)]
    assert key(graph=with_viewpoints) == key()


def test_prompt_edits_invalidate_the_cache(tmp_path):
    """The key uses the rendered system prompt, so template and few-shot edits both count."""
    cache = GroundingCache(tmp_path)

    def call(prompts, script):
        backend = FakeBackend(script)
        out = ground(COMMAND, GRAPH, VOCAB, backend, cache, prompts=prompts,
                     keyword_table=TABLE)
        return out, backend

    base = builder()
    assert call(base, [GOOD_RESPONSE])[0].source == "llm"
    assert call(base, [])[0].source == "cache"
    edited_template = builder(template="SYS2 {scene_graph} | {vocabulary} | {examples}")
    out, backend = call(edited_template, [GOOD_RESPONSE])
    assert out.source == "llm" and len(backend.calls) == 1
    edited_examples = builder(examples=[FewShotExample("another example", GOOD_RESPONSE)])
    out, backend = call(edited_examples, [GOOD_RESPONSE])
    assert out.source == "llm" and len(backend.calls) == 1


def test_model_name_invalidates_the_cache(tmp_path):
    cache = GroundingCache(tmp_path)
    ground(COMMAND, GRAPH, VOCAB, FakeBackend([GOOD_RESPONSE], model="a"), cache,
           prompts=builder(), keyword_table=TABLE)
    other = FakeBackend([GOOD_RESPONSE], model="b")
    out = ground(COMMAND, GRAPH, VOCAB, other, cache, prompts=builder(), keyword_table=TABLE)
    assert out.source == "llm" and len(other.calls) == 1 and out.model == "b"


# ----------------------------------------------------------------- log

def read_log(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_log_record_for_retry_then_success(tmp_path):
    log = tmp_path / "logs" / "g.jsonl"
    run([BAD_RESPONSE, GOOD_RESPONSE], logger=GroundingLogger(log))
    (record,) = read_log(log)
    assert record["command"] == COMMAND
    assert record["model"] == "fake-model"
    assert record["cache_hit"] is False
    assert record["source"] == "llm"
    assert record["attempts"] == 2
    assert len(record["raw_responses"]) == 2
    assert record["validation_errors"][0]["attempt"] == 1
    assert record["validation_errors"][0]["errors"]
    assert record["validation_errors"][1]["errors"] == []
    assert record["backend_errors"] == []
    assert len(record["backend_latencies_s"]) == 2
    assert record["latency_s"] >= 0
    assert record["timestamp"].endswith("+00:00")
    assert record["result"]["targets"] == ["banana", "apple"]


def test_log_has_one_line_per_call_including_cache_hits_and_fallbacks(tmp_path):
    log = tmp_path / "g.jsonl"
    logger = GroundingLogger(log)
    cache = GroundingCache(tmp_path / "cache")
    run([GOOD_RESPONSE], cache=cache, logger=logger)
    run([], cache=cache, logger=logger)
    run([BackendTimeoutError("slow")], command="find the apple", logger=logger)
    records = read_log(log)
    assert [r["source"] for r in records] == ["llm", "cache", "fallback"]
    assert records[1]["cache_hit"] is True and records[1]["attempts"] == 0
    assert "BackendTimeoutError" in records[2]["backend_errors"][0]


def test_log_never_contains_the_api_key(tmp_path, monkeypatch):
    secret = "sk-very-secret-value-12345"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    log = tmp_path / "g.jsonl"
    run([f"garbage containing {secret}", f"more {secret}"], logger=GroundingLogger(log))
    text = log.read_text()
    assert secret not in text
    assert "[REDACTED]" in text


def test_logger_explicit_secrets(tmp_path):
    log = tmp_path / "g.jsonl"
    GroundingLogger(log, secrets=["hunter2"]).log({"a": ["x hunter2 y"], "b": {"c": "hunter2"}})
    assert "hunter2" not in log.read_text()


# ----------------------------------------------------------------- CLI

def test_cli_with_fake_backend(capsys):
    code = main([COMMAND, "--backend", "fake", "--no-cache", "--no-log"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["source"] == "llm"
    assert data["model"] == "fake-model"
    assert data["result"]["targets"] == [VOCAB[0]]


def test_cli_gemini_without_key_is_a_config_error(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    code = main([COMMAND, "--backend", "gemini", "--no-cache", "--no-log"])
    assert code == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_cli_empty_command(capsys):
    assert main(["  ", "--no-cache", "--no-log"]) == 2
    assert "ERROR" in capsys.readouterr().err


# ----------------------------------------------------------------- fallback reason, backend latency

def test_llm_outcome_reports_the_backend_latency_of_the_successful_attempt():
    backend = FakeBackend([BAD_RESPONSE, GOOD_RESPONSE], latency_s=0.25)
    outcome = ground(COMMAND, GRAPH, VOCAB, backend, prompts=builder(), keyword_table=TABLE)
    assert outcome.source == "llm" and outcome.attempts == 2
    assert outcome.backend_latency_s == 0.25  # one attempt, not the 0.5 s of both
    assert outcome.fallback_reason is None
    assert outcome.to_dict()["backend_latency_s"] == 0.25
    assert outcome.to_dict()["fallback_reason"] is None


@pytest.mark.parametrize("error", [
    BackendTimeoutError("slow"), BackendRateLimitError("quota"), BackendResponseError("garbled"),
])
def test_fallback_reason_backend_error(error):
    outcome, _ = run([error])
    assert outcome.source == "fallback"
    assert outcome.fallback_reason == "backend_error"
    assert outcome.backend_latency_s is None


def test_fallback_reason_invalid_output():
    outcome, _ = run([BAD_RESPONSE, BAD_RESPONSE])
    assert outcome.fallback_reason == "invalid_output"
    assert outcome.backend_latency_s is None


def test_fallback_reason_when_the_retry_hits_a_backend_error():
    outcome, _ = run([BAD_RESPONSE, BackendTimeoutError("slow")])
    assert outcome.source == "fallback" and outcome.attempts == 2
    assert outcome.fallback_reason == "backend_error"  # the last thing that happened


def test_cache_hit_has_no_fallback_reason_or_backend_latency(tmp_path):
    cache = GroundingCache(tmp_path)
    run([GOOD_RESPONSE], cache=cache)
    outcome, _ = run([], cache=cache)
    assert outcome.source == "cache"
    assert outcome.fallback_reason is None and outcome.backend_latency_s is None


def test_log_records_the_fallback_reason_and_backend_latency(tmp_path):
    log = tmp_path / "g.jsonl"
    logger = GroundingLogger(log)
    run([BAD_RESPONSE, BAD_RESPONSE], logger=logger)
    run([BackendTimeoutError("slow")], logger=logger)
    ground(COMMAND, GRAPH, VOCAB, FakeBackend([GOOD_RESPONSE], latency_s=0.25), logger=logger,
           prompts=builder(), keyword_table=TABLE)
    invalid, backend_error, ok = read_log(log)
    assert invalid["fallback_reason"] == "invalid_output" and invalid["backend_latency_s"] is None
    assert backend_error["fallback_reason"] == "backend_error"
    assert ok["fallback_reason"] is None and ok["backend_latency_s"] == 0.25
