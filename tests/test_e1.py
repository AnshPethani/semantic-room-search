import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lang_grounding.backends import (
    BackendRateLimitError,
    BackendTimeoutError,
    FakeBackend,
)
from lang_grounding.config import ConfigError, load_config
from lang_grounding.e1 import (
    ALL_METHODS,
    CSV_COLUMNS,
    CallRow,
    E1Error,
    LabelGateError,
    aggregate_rows,
    check_constraint,
    command_types,
    main,
    parse_methods,
    percentile,
    rank_rooms,
    run_experiment,
    topk_hit,
)
from lang_grounding.e1_labels import load_e1_commands
from lang_grounding.ground import ground
from lang_grounding.grounding_output import load_vocabulary
from lang_grounding.keyword_fallback import load_keyword_table
from lang_grounding.prompts import PromptBuilder
from lang_grounding.scene_graph import load_scene_graph

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config()
GRAPH = load_scene_graph(CONFIG.resolve(CONFIG.paths.scene_graph))
ROOMS = GRAPH.room_ids
VOCAB = load_vocabulary(CONFIG.resolve(CONFIG.paths.vocabulary))
TABLE = load_keyword_table(CONFIG.resolve(CONFIG.paths.keyword_table))
COMMANDS = load_e1_commands(ROOT / "data" / "e1_commands.json")
BY_ID = {c.id: c for c in COMMANDS}
PROMPTS = PromptBuilder("{scene_graph}\n{vocabulary}\n{examples}")
FIXED_NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
STAMP = "20261115T120000Z"


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now


def resp(top, constraint=None):
    prior = {r: 0.06 for r in ROOMS}
    prior[top] = 0.7
    return {"targets": ["banana"], "room_prior": prior, "room_constraint": constraint,
            "rationale": f"top is {top}"}


BAD = {**resp("K"), "targets": ["mug"]}  # invalid: not in the vocabulary


def write_labels(tmp_path, commands, labels=None):
    labels = labels or {}
    path = tmp_path / "labels.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "command", *ROOMS, "notes"])
        for c in commands:
            default = {c.expected_constraint[0]} if c.expected_constraint else {"K"}
            chosen = labels.get(c.id, default)
            writer.writerow([c.id, c.command, *("1" if r in chosen else "" for r in ROOMS), ""])
    return path


def run(tmp_path, ids, methods, backends=None, labels=None, ft=None, **kwargs):
    commands = [BY_ID[i] for i in ids]
    ft = ft or FakeTime()
    options = {
        "config": CONFIG, "graph": GRAPH, "vocabulary": VOCAB, "commands": commands,
        "labels_path": write_labels(tmp_path, commands, labels),
        "methods": parse_methods(methods), "out_dir": tmp_path / "out",
        "backends": backends or {}, "prompts": PROMPTS, "keyword_table": TABLE,
        "min_interval_s": 0.0, "backoff_s": 30.0, "sleep": ft.sleep, "clock": ft.clock,
        "now": lambda: FIXED_NOW,
    }
    options.update(kwargs)
    return run_experiment(**options), ft


# ----------------------------------------------------------------- scoring

PRIOR = {"K": 0.5, "D": 0.3, "LR": 0.1, "E": 0.05, "B1": 0.03, "B2": 0.02}


@pytest.mark.parametrize("labeled, top1, top2", [
    ({"K"}, 1.0, 1.0),
    ({"D"}, 0.0, 1.0),
    ({"LR"}, 0.0, 0.0),
    ({"B2"}, 0.0, 0.0),
    ({"D", "B2"}, 0.0, 1.0),
])
def test_topk_without_ties(labeled, top1, top2):
    assert topk_hit(PRIOR, labeled, 1) == top1
    assert topk_hit(PRIOR, labeled, 2) == top2


def test_topk_tie_at_the_cutoff_uses_the_expected_value():
    prior = {"K": 0.4, "D": 0.3, "LR": 0.3, "E": 0.0, "B1": 0.0, "B2": 0.0}
    assert topk_hit(prior, {"LR"}, 1) == 0.0
    assert topk_hit(prior, {"LR"}, 2) == pytest.approx(0.5)  # D and LR tie for one slot
    assert topk_hit(prior, {"D", "LR"}, 2) == 1.0
    assert topk_hit(prior, {"E"}, 2) == 0.0


def test_topk_tie_for_first_place():
    prior = {"K": 0.4, "D": 0.4, "LR": 0.2, "E": 0.0, "B1": 0.0, "B2": 0.0}
    assert topk_hit(prior, {"D"}, 1) == pytest.approx(0.5)
    assert topk_hit(prior, {"D"}, 2) == 1.0  # both tied rooms fit into the top two
    assert topk_hit(prior, {"LR"}, 2) == 0.0


def test_topk_uniform_baseline():
    uniform = {r: 1 / 6 for r in ROOMS}
    assert topk_hit(uniform, {"K", "D"}, 1) == pytest.approx(2 / 6)
    assert topk_hit(uniform, {"K", "D"}, 2) == pytest.approx(0.6)  # 1 - C(4,2)/C(6,2)
    assert topk_hit(uniform, {"K"}, 1) == pytest.approx(1 / 6)
    assert topk_hit(uniform, {"K"}, 2) == pytest.approx(2 / 6)
    assert topk_hit(uniform, set(ROOMS), 1) == 1.0


def test_topk_ties_are_detected_within_a_tolerance():
    prior = {"K": 0.5, "D": 0.25 + 1e-12, "LR": 0.25, "E": 0.0, "B1": 0.0, "B2": 0.0}
    assert topk_hit(prior, {"LR"}, 2) == pytest.approx(0.5)


def test_topk_rejects_bad_k_and_handles_no_labels():
    with pytest.raises(ValueError):
        topk_hit(PRIOR, {"K"}, 0)
    assert topk_hit(PRIOR, set(), 2) == 0.0


def test_rank_rooms_breaks_ties_in_graph_order():
    prior = {"K": 0.2, "D": 0.4, "LR": 0.2, "E": 0.2, "B1": 0.0, "B2": 0.0}
    assert rank_rooms(prior, ROOMS) == ["D", "E", "K", "LR", "B1", "B2"]


# ----------------------------------------------------------------- constraint check

def test_constraint_check():
    assert check_constraint(None, None) is True
    assert check_constraint(None, ["K"]) is False  # no constraint expected, one given
    assert check_constraint(("E", "LR"), ["LR", "E"]) is True  # set match, order ignored
    assert check_constraint(("E", "LR"), ["E"]) is False
    assert check_constraint(("E", "LR"), ["E", "LR", "K"]) is False
    assert check_constraint(("E", "LR"), None) is False


# ----------------------------------------------------------------- aggregation

def make_row(top1=1.0, top2=1.0, *, constrained=False, ok=True, latency=None, source="llm",
             reason=None, type_="explicit", method="gemini_full"):
    return CallRow(
        id="x", type=type_, command="c", method=method, source=source, attempts=1, passes=1,
        top1=top1, top2=top2, constrained=constrained, constraint_ok=ok, latency_s=latency,
        labeled=("K",), ranked=(), prior={}, targets=(), rationale="", fallback_reason=reason,
        expected_constraint=("LR",) if constrained else None, room_constraint=None)


def test_percentile():
    assert percentile([], 0.5) is None
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([5, 1, 4, 2, 3], 0.95) == pytest.approx(4.8)
    assert percentile([1, 2, 3, 4], 0.95) == pytest.approx(3.85)


def test_aggregate_rows():
    rows = [
        make_row(1.0, 1.0, constrained=True, ok=True, latency=1.0),
        make_row(0.0, 1.0, constrained=True, ok=False, latency=2.0),
        make_row(1.0, 1.0, constrained=False, ok=True, latency=3.0),
        make_row(0.5, 1.0, constrained=False, ok=False, latency=4.0),
        make_row(0.0, 0.0, constrained=False, ok=False, source="fallback",
                 reason="invalid_output"),
        make_row(0.0, 0.0, constrained=True, ok=False, source="fallback",
                 reason="backend_error"),
    ]
    s = aggregate_rows(rows)
    assert s.n == 6
    assert s.top1 == pytest.approx(2.5 / 6)  # misses count as 0
    assert s.top2 == pytest.approx(4 / 6)
    assert s.n_constrained == 3 and s.constraint_match == pytest.approx(1 / 3)
    assert s.n_unconstrained == 3 and s.constraint_null == pytest.approx(1 / 3)
    assert s.n_latency == 4  # fallback rows have no LLM latency
    assert s.latency_mean == pytest.approx(2.5)
    assert s.latency_median == pytest.approx(2.5)
    assert s.latency_p95 == pytest.approx(3.85)
    assert s.fallback_rows == 2
    assert s.invalid_output_rows == 1
    assert s.invalid_output_rate == pytest.approx(1 / 6)


def test_aggregate_non_llm_rows_have_no_constraint_or_latency_stats():
    s = aggregate_rows([make_row(ok=None, source="keyword"), make_row(ok=None, source="keyword")])
    assert s.constraint_match is None and s.constraint_null is None
    assert s.latency_mean is None and s.n_latency == 0
    assert s.top1 == 1.0


def test_aggregate_empty():
    s = aggregate_rows([])
    assert s.n == 0 and s.top1 is None and s.invalid_output_rate is None


def test_command_types_in_report_order():
    assert command_types(COMMANDS) == ["explicit", "category", "need", "relational"]


def test_parse_methods():
    assert [m.name for m in parse_methods(None)] == list(ALL_METHODS)
    specs = parse_methods(["ollama_names_only", "keyword", "ollama_names_only"])
    assert [m.name for m in specs] == ["ollama_names_only", "keyword"]
    assert (specs[0].kind, specs[0].provider, specs[0].style) == ("llm", "ollama", "names_only")
    assert specs[1].kind == "keyword"
    for bad in ("gpt_full", "gemini", "gemini_partial", "Keyword"):
        with pytest.raises(E1Error, match="unknown method"):
            parse_methods([bad])


# ----------------------------------------------------------------- label gate

def test_invalid_labels_refuse_to_run(tmp_path):
    commands = [BY_ID["e1_01"], BY_ID["e1_28"]]
    labels_path = write_labels(tmp_path, commands, {"e1_28": {"D"}})  # D is not next to K
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)

    with pytest.raises(LabelGateError, match="label validation failed") as info:
        run_experiment(
            config=CONFIG, graph=GRAPH, vocabulary=VOCAB, commands=commands,
            labels_path=labels_path, methods=parse_methods(["gemini_full"]),
            out_dir=tmp_path / "out", backends={"gemini": FakeBackend()}, prompts=PROMPTS,
            keyword_table=TABLE, ground_fn=spy)
    assert "e1_28" in str(info.value) and "room D" in str(info.value)
    assert calls == []
    assert not (tmp_path / "out").exists()  # nothing was created


def test_missing_label_file_refuses_to_run(tmp_path):
    with pytest.raises(LabelGateError, match="cannot read"):
        run(tmp_path, ["e1_01"], ["uniform"], labels_path=tmp_path / "nope.csv")


# ----------------------------------------------------------------- baselines

def test_keyword_and_uniform_methods_need_no_backend(tmp_path):
    result, ft = run(tmp_path, ["e1_01", "e1_10"], ["keyword", "uniform"],
                     ground_fn=lambda *a, **k: pytest.fail("ground() must not be called"))
    by = {(r.method, r.id): r for r in result.rows}
    assert by["keyword", "e1_01"].source == "keyword"
    assert by["keyword", "e1_01"].top1 == 1.0  # banana: kitchen first, labeled K
    assert by["keyword", "e1_01"].constraint_ok is None
    assert by["keyword", "e1_01"].latency_s is None
    assert by["uniform", "e1_01"].top1 == pytest.approx(1 / 6)  # one labeled room
    assert by["uniform", "e1_01"].top2 == pytest.approx(2 / 6)
    assert by["uniform", "e1_01"].source == "uniform"
    assert ft.sleeps == []


# ----------------------------------------------------------------- LLM runs, scoring and wiring

def test_llm_row_is_scored_from_the_llm_answer(tmp_path):
    backend = FakeBackend([resp("K"), resp("LR", ["E", "LR"]), resp("D", ["LR"])], latency_s=0.25)
    result, _ = run(tmp_path, ["e1_01", "e1_28", "e1_31"], ["gemini_full"],
                    backends={"gemini": backend}, labels={"e1_28": {"E"}})
    r1, r28, r31 = result.rows
    assert (r1.source, r1.attempts, r1.passes) == ("llm", 1, 1)
    assert r1.top1 == 1.0 and r1.constraint_ok is True  # unconstrained and null
    assert r1.latency_s == 0.25
    assert r1.ranked[0] == "K" and r1.targets == ("banana",) and r1.rationale == "top is K"
    # E is labeled but LR is ranked first; E ties with 4 other rooms for the second place
    assert r28.top1 == 0.0 and r28.top2 == pytest.approx(0.2)
    assert r28.constraint_ok is True  # {E, LR} matches exactly
    assert r31.constraint_ok is True and r31.top1 == 0.0  # LR labeled, D ranked first


def test_unconstrained_command_with_a_constraint_is_wrong(tmp_path):
    backend = FakeBackend([resp("K", ["K"])])
    result, _ = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": backend})
    assert result.rows[0].constraint_ok is False
    assert result.rows[0].top1 == 1.0


def test_cache_is_never_used_and_variants_get_their_own_prompts(tmp_path):
    seen = []

    def spy(command, graph, vocabulary, backend, cache=None, logger=None, **kwargs):
        seen.append({"cache": cache, "style": kwargs["prompts"].scene_graph_style,
                     "backend": backend})
        return ground(command, graph, vocabulary, backend, cache, logger, **kwargs)

    backends = {"gemini": FakeBackend(model="g"), "ollama": FakeBackend(model="o")}
    run(tmp_path, ["e1_01", "e1_05"],
        ["gemini_full", "gemini_names_only", "ollama_full", "ollama_names_only"],
        backends=backends, ground_fn=spy)
    assert len(seen) == 8
    assert all(s["cache"] is None for s in seen)  # no cache lookup, no cache write
    assert [s["style"] for s in seen] == ["full"] * 2 + ["names_only"] * 2 \
        + ["full"] * 2 + ["names_only"] * 2
    assert [s["backend"].model for s in seen] == ["g"] * 4 + ["o"] * 4
    full_prompts = [c.system_prompt for c in backends["gemini"].calls[:2]]
    names_prompts = [c.system_prompt for c in backends["gemini"].calls[2:]]
    assert all("m^2" in p and "connected by a door" in p for p in full_prompts)
    assert all("m^2" not in p and "door" not in p for p in names_prompts)


def test_names_only_prompt_omits_areas_and_adjacency():
    full = PROMPTS.build("c", GRAPH, VOCAB).system
    names = PROMPTS.with_scene_graph_style("names_only").build("c", GRAPH, VOCAB).system
    assert PROMPTS.with_scene_graph_style("full").build("c", GRAPH, VOCAB).system == full
    for room in GRAPH.rooms:
        assert f"- {room.id}: {room.name}" in names
        assert f"{room.area:.1f}" not in names
    for word in ("m^2", "door", "connected", "adjacent", "next to", "share", "outside"):
        assert word not in names.lower()
    assert "m^2" in full and "connected by a door" in full


def test_unknown_scene_graph_style_is_rejected():
    with pytest.raises(ConfigError, match="unknown scene graph style"):
        PROMPTS.with_scene_graph_style("minimal")


# ----------------------------------------------------------------- pacing and re-runs

def test_calls_to_one_provider_are_paced(tmp_path):
    result, ft = run(tmp_path, ["e1_01", "e1_02", "e1_03"], ["gemini_full"],
                     backends={"gemini": FakeBackend()}, min_interval_s=6.0)
    assert len(result.rows) == 3
    assert ft.sleeps == [6.0, 6.0]  # nothing before the first call


def test_pacing_counts_the_time_a_call_took(tmp_path):
    ft = FakeTime()

    def slow_ground(*args, **kwargs):
        ft.now += 4.0
        return ground(*args, **kwargs)

    run(tmp_path, ["e1_01", "e1_02", "e1_03"], ["gemini_full"],
        backends={"gemini": FakeBackend()}, min_interval_s=6.0, ft=ft, ground_fn=slow_ground)
    assert ft.sleeps == [2.0, 2.0]


def test_pacing_is_tracked_per_provider(tmp_path):
    # each provider waits once (between its own two calls), not when switching providers
    ft = FakeTime()
    run(tmp_path, ["e1_01", "e1_02"], ["gemini_full", "ollama_full"],
        backends={"gemini": FakeBackend(), "ollama": FakeBackend()}, min_interval_s=6.0, ft=ft)
    assert ft.sleeps == [6.0, 6.0]


def test_rerun_after_a_rate_limit_then_success(tmp_path):
    backend = FakeBackend([BackendRateLimitError("quota"), resp("K")], latency_s=0.25)
    result, ft = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": backend},
                     min_interval_s=6.0, backoff_s=30.0)
    (row,) = result.rows
    assert row.source == "llm" and row.passes == 2
    assert row.latency_s == 0.25  # the successful attempt only, not the failed pass
    assert row.top1 == 1.0
    assert len(backend.calls) == 2
    assert ft.sleeps == [30.0]  # one backoff; the 6 s pacing had already elapsed
    records = [json.loads(line) for line in
               (result.run_dir / "calls.jsonl").read_text().splitlines()]
    assert [r["pass"] for r in records] == [1, 2]
    assert [r["source"] for r in records] == ["fallback", "llm"]
    assert records[0]["fallback_reason"] == "backend_error"
    assert records[0]["method"] == "gemini_full" and records[0]["command_id"] == "e1_01"


def test_backoff_doubles_between_passes(tmp_path):
    backend = FakeBackend([BackendTimeoutError("t"), BackendRateLimitError("q"), resp("K")])
    result, ft = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": backend},
                     backoff_s=30.0, max_passes=3)
    assert result.rows[0].source == "llm" and result.rows[0].passes == 3
    assert ft.sleeps == [30.0, 60.0]


def test_gives_up_after_max_passes_and_lists_the_command(tmp_path):
    backend = FakeBackend([BackendTimeoutError("t"), BackendRateLimitError("q"), resp("K")])
    result, ft = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": backend},
                     backoff_s=30.0, max_passes=2)
    (row,) = result.rows
    assert row.source == "fallback" and row.fallback_reason == "backend_error"
    assert row.passes == 2 and row.top1 == 0.0 and row.top2 == 0.0
    assert row.ranked == () and row.targets == () and row.latency_s is None
    assert row.constraint_ok is False  # never answered: a miss
    assert ft.sleeps == [30.0]
    summary = result.paths["summary"].read_text()
    assert "Commands without an LLM answer" in summary
    assert "e1_01 (backend_error, 2 passes)" in summary


def test_invalid_output_is_a_miss_and_is_not_rerun(tmp_path):
    backend = FakeBackend([BAD, BAD, resp("K")])  # ground() retries once itself
    result, ft = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": backend})
    (row,) = result.rows
    assert row.source == "fallback" and row.fallback_reason == "invalid_output"
    assert row.passes == 1 and row.attempts == 2
    assert len(backend.calls) == 2  # the third scripted answer was never requested
    assert ft.sleeps == []
    # the keyword fallback would have found the kitchen, but it is never scored as an LLM result
    assert row.top1 == 0.0 and row.ranked == () and row.targets == ()
    s = aggregate_rows(result.rows)
    assert s.invalid_output_rows == 1 and s.invalid_output_rate == 1.0 and s.top1 == 0.0
    assert "e1_01 (invalid_output, 1 pass)" in result.paths["summary"].read_text()


# ----------------------------------------------------------------- outputs

def test_outputs_are_written(tmp_path):
    backends = {"gemini": FakeBackend([resp("K"), resp("D"), resp("K"), resp("D")],
                                      latency_s=0.25, model="gemini-test")}
    result, _ = run(tmp_path, ["e1_01", "e1_10"],
                    ["keyword", "uniform", "gemini_full", "gemini_names_only"],
                    backends=backends)
    assert result.run_dir == tmp_path / "out" / STAMP
    assert set(result.paths) == {"calls", "per_command", "summary", "failures"}
    assert all(p.parent == result.run_dir and p.exists() for p in result.paths.values())

    with result.paths["per_command"].open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == CSV_COLUMNS
    assert CSV_COLUMNS[:12] == ["id", "type", "method", "source", "attempts", "top1", "top2",
                                "constraint_ok", "latency_s", "ranked_rooms", "targets",
                                "rationale"]
    assert len(rows) == 8  # 2 commands x 4 methods
    llm = next(r for r in rows if r["method"] == "gemini_full" and r["id"] == "e1_01")
    assert llm["source"] == "llm" and llm["constraint_ok"] == "1"
    assert llm["latency_s"] == "0.2500" and llm["ranked_rooms"].split()[0] == "K"
    assert llm["targets"] == "banana" and llm["rationale"] == "top is K"
    base = next(r for r in rows if r["method"] == "uniform" and r["id"] == "e1_01")
    assert base["constraint_ok"] == "" and base["latency_s"] == ""

    calls = [json.loads(x) for x in result.paths["calls"].read_text().splitlines()]
    assert len(calls) == 8  # one record per call, baselines included
    assert {c["method"] for c in calls} == {"keyword", "uniform", "gemini_full",
                                            "gemini_names_only"}

    summary = result.paths["summary"].read_text()
    for heading in ("## Overall", "## By command type", "### explicit", "### category",
                    "## Scene-graph ablation", "## Hosted vs local latency",
                    "## Commands without an LLM answer", "## Scoring"):
        assert heading in summary
    assert "DRY RUN" not in summary
    assert "hosted (gemini)" in summary and "gemini-test" in summary
    assert "None: every LLM command got an answer." in summary

    failures = result.paths["failures"].read_text()
    assert "# E1 top-1 misses" in failures
    assert "### e1_01 (explicit): find the banana" in failures  # uniform misses this one
    assert "- labeled: K" in failures


def test_failures_list_the_misses_of_an_llm_method(tmp_path):
    backend = FakeBackend([resp("D", ["K"])])  # wrong room and a constraint where none is expected
    result, _ = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": backend})
    failures = result.paths["failures"].read_text()
    assert "## gemini_full (1 of 1)" in failures
    assert "- labeled: K" in failures
    assert "- ranked: D 0.700" in failures
    assert "- rationale: top is D" in failures
    assert "- constraint: expected null; got K" in failures


def test_dry_run_is_marked_in_the_summary(tmp_path):
    result, _ = run(tmp_path, ["e1_01"], ["gemini_full"], backends={"gemini": FakeBackend()},
                    dry_run=True)
    assert "DRY RUN" in result.paths["summary"].read_text()


def test_bad_run_options(tmp_path):
    with pytest.raises(E1Error, match="max_passes"):
        run(tmp_path, ["e1_01"], ["uniform"], max_passes=0)
    with pytest.raises(E1Error, match="negative"):
        run(tmp_path, ["e1_01"], ["uniform"], backoff_s=-1)


# ----------------------------------------------------------------- CLI

def full_labels(tmp_path, labels=None):
    return write_labels(tmp_path, COMMANDS, labels)


def test_cli_dry_run(tmp_path, capsys):
    out_dir = tmp_path / "results"
    code = main(["run", "--dry-run", "--labels", str(full_labels(tmp_path)),
                 "--out-dir", str(out_dir)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "Results:" in printed
    (run_dir,) = list(out_dir.iterdir())
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "calls.jsonl", "failures.md", "per_command.csv", "summary.md"]
    assert str(run_dir / "summary.md") in printed
    assert "DRY RUN" in (run_dir / "summary.md").read_text()
    with (run_dir / "per_command.csv").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == len(COMMANDS) * len(ALL_METHODS)


def test_cli_methods_subset(tmp_path, capsys):
    out_dir = tmp_path / "results"
    code = main(["run", "--methods", "keyword, uniform", "--labels",
                 str(full_labels(tmp_path)), "--out-dir", str(out_dir)])
    assert code == 0
    (run_dir,) = list(out_dir.iterdir())
    with (run_dir / "per_command.csv").open(encoding="utf-8", newline="") as f:
        assert {r["method"] for r in csv.DictReader(f)} == {"keyword", "uniform"}
    capsys.readouterr()


def test_cli_refuses_invalid_labels(tmp_path, capsys):
    labels = full_labels(tmp_path, {"e1_28": {"D"}})
    code = main(["run", "--dry-run", "--labels", str(labels), "--out-dir",
                 str(tmp_path / "results")])
    assert code == 1
    assert "label validation failed" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_cli_missing_labels_file(tmp_path, capsys):
    code = main(["run", "--dry-run", "--labels", str(tmp_path / "nope.csv"), "--out-dir",
                 str(tmp_path / "results")])
    assert code == 1
    assert "cannot read" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--methods", "gpt_full"], ["--max-passes", "0"]])
def test_cli_option_errors(tmp_path, capsys, extra):
    code = main(["run", "--dry-run", "--labels", str(full_labels(tmp_path)), "--out-dir",
                 str(tmp_path / "results"), *extra])
    assert code == 2
    assert "ERROR:" in capsys.readouterr().err
