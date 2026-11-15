"""E1 grounding experiment (D-123 to D-127). Pure Python, no ROS.

Compares the room rankings of several methods with the rooms the team labeled plausible:
a keyword baseline, a uniform baseline, and the LLM (hosted Gemini and local Ollama), each with
the full scene graph and with room IDs and names only (the scene-graph ablation).

    python -m lang_grounding.e1 run --dry-run --out-dir /tmp/e1_dry      # fake backend
    python -m lang_grounding.e1 run --methods gemini_full,gemini_names_only
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lang_grounding.backends import Backend, FakeBackend, create_backend
from lang_grounding.config import REPO_ROOT, GroundingConfig, load_config
from lang_grounding.e1_labels import (
    DEFAULT_COMMANDS_PATH,
    E1Command,
    LabelsError,
    load_e1_commands,
    validate_labels,
)
from lang_grounding.ground import GroundOutcome, ground
from lang_grounding.grounding_log import GroundingLogger
from lang_grounding.grounding_output import load_vocabulary
from lang_grounding.keyword_fallback import KeywordTable, keyword_ground, load_keyword_table
from lang_grounding.prompts import SCENE_GRAPH_STYLES, PromptBuilder
from lang_grounding.scene_graph import SceneGraph, load_scene_graph

DEFAULT_LABELS_PATH = REPO_ROOT / "data" / "e1_labels_final.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "results" / "e1"
ALL_METHODS = (
    "keyword", "uniform",
    "gemini_full", "gemini_names_only", "ollama_full", "ollama_names_only",
)
PROVIDER_KIND = {"gemini": "hosted", "ollama": "local"}
TYPE_ORDER = ("explicit", "category", "need", "relational")
TIE_TOL = 1e-9


class E1Error(ValueError):
    """Bad options or a failed precondition for the experiment."""


class LabelGateError(E1Error):
    """The label file failed validation, so the experiment refuses to run."""


# --------------------------------------------------------------------------- methods

@dataclass(frozen=True)
class MethodSpec:
    name: str
    kind: str  # "keyword", "uniform" or "llm"
    provider: str | None = None  # "gemini" or "ollama" for LLM methods
    style: str | None = None  # "full" or "names_only" for LLM methods


def parse_method(name: str) -> MethodSpec:
    if name in ("keyword", "uniform"):
        return MethodSpec(name, name)
    provider, _, style = name.partition("_")
    if provider in PROVIDER_KIND and style in SCENE_GRAPH_STYLES:
        return MethodSpec(name, "llm", provider, style)
    raise E1Error(f"unknown method {name!r}; choose from {', '.join(ALL_METHODS)}")


def parse_methods(names: Sequence[str] | None) -> list[MethodSpec]:
    """Method specs in the order given (default: all), without duplicates."""
    selected = list(ALL_METHODS) if not names else list(dict.fromkeys(names))
    return [parse_method(n) for n in selected]


# --------------------------------------------------------------------------- scoring

def rank_rooms(prior: Mapping[str, float], room_ids: Sequence[str]) -> list[str]:
    """Rooms by descending probability; ties in scene-graph order (for display only)."""
    order = {r: i for i, r in enumerate(room_ids)}
    return sorted(prior, key=lambda r: (-prior[r], order.get(r, len(order))))


def topk_hit(prior: Mapping[str, float], labeled: Collection[str], k: int) -> float:
    """Probability that the top k rooms contain a labeled room, with random tie-breaking.

    Rooms are ranked by descending prior. Rooms with equal priors (within 1e-9) are tied; the
    tied rooms that straddle the cut-off are chosen uniformly at random, so the result is the
    expected value of the 0/1 hit indicator: exactly 0 or 1 without ties at the cut-off, and a
    fraction with them. For a uniform prior with 2 labeled rooms of 6, top-1 is 2/6 and top-2
    is 1 - C(4,2)/C(6,2) = 0.6.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    ordered = sorted(prior.items(), key=lambda kv: -kv[1])
    remaining = k
    i = 0
    while i < len(ordered) and remaining > 0:
        j = i + 1
        while j < len(ordered) and ordered[i][1] - ordered[j][1] <= TIE_TOL:
            j += 1
        size = j - i
        labeled_in_group = sum(1 for room, _ in ordered[i:j] if room in labeled)
        if remaining >= size:  # the whole tie group is inside the top k
            if labeled_in_group:
                return 1.0
            remaining -= size
        else:  # the cut-off falls inside the group: `remaining` of its rooms are drawn at random
            return 1.0 - (math.comb(size - labeled_in_group, remaining)
                          / math.comb(size, remaining))
        i = j
    return 0.0


def check_constraint(
    expected: Sequence[str] | None, actual: Sequence[str] | None
) -> bool:
    """Exact set match when a constraint is expected; otherwise room_constraint must be null."""
    if expected is None:
        return actual is None
    return actual is not None and set(actual) == set(expected)


def percentile(values: Sequence[float], q: float) -> float | None:
    """The q-quantile (0 to 1) with linear interpolation between order statistics."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


# --------------------------------------------------------------------------- rows

@dataclass(frozen=True)
class CallRow:
    """One scored (command, method) result."""

    id: str
    type: str
    command: str
    method: str
    source: str  # "llm", "fallback" (no LLM answer), "keyword" or "uniform"
    attempts: int
    passes: int
    top1: float
    top2: float
    constrained: bool  # the command has an expected_constraint
    constraint_ok: bool | None  # None for the non-LLM methods
    latency_s: float | None  # backend latency of the successful attempt (LLM answers only)
    labeled: tuple[str, ...]
    ranked: tuple[str, ...]
    prior: dict[str, float]
    targets: tuple[str, ...]
    rationale: str
    fallback_reason: str | None
    expected_constraint: tuple[str, ...] | None
    room_constraint: tuple[str, ...] | None
    no_keyword_match: bool = False
    model: str = ""

    @property
    def no_llm_answer(self) -> bool:
        return self.source == "fallback"


def _make_row(
    cmd: E1Command,
    spec: MethodSpec,
    labeled: frozenset[str],
    room_ids: Sequence[str],
    *,
    source: str,
    passes: int = 1,
    attempts: int = 0,
    prior: Mapping[str, float] | None = None,
    latency_s: float | None = None,
    targets: Sequence[str] = (),
    rationale: str = "",
    room_constraint: Sequence[str] | None = None,
    fallback_reason: str | None = None,
    no_keyword_match: bool = False,
    model: str = "",
) -> CallRow:
    """Score a result. Without a prior (no LLM answer) both top-k scores are 0: a miss."""
    has_answer = prior is not None
    if has_answer:
        top1 = topk_hit(prior, labeled, 1)
        top2 = topk_hit(prior, labeled, 2)
        ranked = tuple(rank_rooms(prior, room_ids))
    else:
        top1 = top2 = 0.0
        ranked = ()
    constraint_ok = None
    if spec.kind == "llm":
        constraint_ok = has_answer and check_constraint(cmd.expected_constraint, room_constraint)
    return CallRow(
        id=cmd.id, type=cmd.type, command=cmd.command, method=spec.name, source=source,
        attempts=attempts, passes=passes, top1=top1, top2=top2,
        constrained=cmd.expected_constraint is not None, constraint_ok=constraint_ok,
        latency_s=latency_s, labeled=tuple(r for r in room_ids if r in labeled), ranked=ranked,
        prior=dict(prior) if prior is not None else {}, targets=tuple(targets),
        rationale=rationale, fallback_reason=fallback_reason,
        expected_constraint=cmd.expected_constraint,
        room_constraint=None if room_constraint is None else tuple(room_constraint),
        no_keyword_match=no_keyword_match, model=model)


# --------------------------------------------------------------------------- aggregation

@dataclass(frozen=True)
class Stats:
    n: int
    top1: float | None
    top2: float | None
    constraint_match: float | None  # over commands with an expected_constraint
    n_constrained: int
    constraint_null: float | None  # over commands without one (room_constraint must be null)
    n_unconstrained: int
    latency_mean: float | None
    latency_median: float | None
    latency_p95: float | None
    n_latency: int
    fallback_rows: int
    invalid_output_rows: int

    @property
    def invalid_output_rate(self) -> float | None:
        return self.invalid_output_rows / self.n if self.n else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_rows(rows: Sequence[CallRow]) -> Stats:
    """Rates over all given rows; a command without an LLM answer counts as a miss."""
    constrained = [r.constraint_ok for r in rows if r.constrained and r.constraint_ok is not None]
    unconstrained = [
        r.constraint_ok for r in rows if not r.constrained and r.constraint_ok is not None]
    latencies = [r.latency_s for r in rows if r.latency_s is not None]
    return Stats(
        n=len(rows),
        top1=_mean([r.top1 for r in rows]),
        top2=_mean([r.top2 for r in rows]),
        constraint_match=_mean([float(x) for x in constrained]),
        n_constrained=len(constrained),
        constraint_null=_mean([float(x) for x in unconstrained]),
        n_unconstrained=len(unconstrained),
        latency_mean=_mean(latencies),
        latency_median=statistics.median(latencies) if latencies else None,
        latency_p95=percentile(latencies, 0.95),
        n_latency=len(latencies),
        fallback_rows=sum(1 for r in rows if r.source == "fallback"),
        invalid_output_rows=sum(1 for r in rows if r.fallback_reason == "invalid_output"),
    )


def command_types(commands: Sequence[E1Command]) -> list[str]:
    present = {c.type for c in commands}
    return [t for t in TYPE_ORDER if t in present] + sorted(present - set(TYPE_ORDER))


# --------------------------------------------------------------------------- the experiment

class _E1Logger(GroundingLogger):
    """GroundingLogger that adds the current method, command and pass to every record."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.context: dict[str, Any] = {}

    def log(self, record: Mapping[str, Any]) -> None:
        super().log({**self.context, **record})


@dataclass(frozen=True)
class E1Result:
    run_dir: Path
    rows: list[CallRow]
    paths: dict[str, Path] = field(default_factory=dict)


GroundFn = Callable[..., GroundOutcome]


def run_experiment(
    *,
    config: GroundingConfig,
    graph: SceneGraph,
    vocabulary: Sequence[str],
    commands: Sequence[E1Command],
    labels_path: str | Path,
    methods: Sequence[MethodSpec],
    out_dir: str | Path,
    backends: Mapping[str, Backend],
    prompts: PromptBuilder,
    keyword_table: KeywordTable,
    min_interval_s: float = 6.0,
    max_passes: int = 3,
    backoff_s: float = 30.0,
    dry_run: bool = False,
    ground_fn: GroundFn = ground,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] | None = None,
    progress: Callable[[str], None] | None = None,
) -> E1Result:
    """Run the experiment and write its outputs under `out_dir/<UTC timestamp>/` (D-123..127).

    Refuses to run (LabelGateError, nothing written) if the label file fails validation.
    LLM calls never read or write the cache. Calls to one provider start at least
    `min_interval_s` apart. A command whose LLM call ended in a fallback caused by a backend
    error is re-run after a backoff (backoff_s, doubling), up to `max_passes` passes in total; a
    fallback caused by invalid output is a real miss and is not re-run.
    """
    say = progress or (lambda _msg: None)
    if max_passes < 1:
        raise E1Error("max_passes must be at least 1")
    if min_interval_s < 0 or backoff_s < 0:
        raise E1Error("min_interval_s and backoff_s must not be negative")

    room_ids = graph.room_ids
    try:
        report = validate_labels(labels_path, commands, room_ids)
    except LabelsError as exc:
        raise LabelGateError(str(exc)) from exc
    if report.errors:
        raise LabelGateError(
            "label validation failed, not running:\n" + "\n".join(report.errors))
    for warning in report.warnings:
        say(f"WARNING: {warning}")
    labels = report.labels

    stamp = (now or (lambda: datetime.now(UTC)))().strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(out_dir) / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    logger = _E1Logger(run_dir / "calls.jsonl")

    last_start: dict[str, float] = {}

    def pace(provider: str) -> None:
        """Wait so that calls to the same provider start at least min_interval_s apart."""
        previous = last_start.get(provider)
        if previous is not None and min_interval_s > 0:
            wait = min_interval_s - (clock() - previous)
            if wait > 0:
                sleep(wait)
        last_start[provider] = clock()

    def run_llm(spec: MethodSpec, cmd: E1Command) -> CallRow:
        assert spec.provider is not None and spec.style is not None
        backend = backends[spec.provider]
        builder = prompts.with_scene_graph_style(spec.style)
        outcome: GroundOutcome | None = None
        passes = 0
        while passes < max_passes:
            passes += 1
            pace(spec.provider)
            logger.context = {"method": spec.name, "command_id": cmd.id, "type": cmd.type,
                              "pass": passes}
            outcome = ground_fn(
                cmd.command, graph, vocabulary, backend, None, logger,
                prompts=builder, keyword_table=keyword_table, floor=config.floor)
            if outcome.source == "cache":
                raise E1Error("ground() returned a cached result; E1 must not use the cache")
            retry = (outcome.source == "fallback" and outcome.fallback_reason == "backend_error"
                     and passes < max_passes)
            if not retry:
                break
            sleep(backoff_s * 2 ** (passes - 1))
        assert outcome is not None
        labeled = labels[cmd.id]
        if outcome.source == "llm":
            return _make_row(
                cmd, spec, labeled, room_ids, source="llm", passes=passes,
                attempts=outcome.attempts, prior=outcome.result.room_prior,
                latency_s=outcome.backend_latency_s, targets=outcome.result.targets,
                rationale=outcome.result.rationale,
                room_constraint=outcome.result.room_constraint, model=outcome.model)
        # No LLM answer: a miss. The keyword-fallback result is never scored as an LLM result.
        return _make_row(
            cmd, spec, labeled, room_ids, source="fallback", passes=passes,
            attempts=outcome.attempts, fallback_reason=outcome.fallback_reason,
            model=outcome.model)

    def run_baseline(spec: MethodSpec, cmd: E1Command) -> CallRow:
        labeled = labels[cmd.id]
        logger.context = {"method": spec.name, "command_id": cmd.id, "type": cmd.type, "pass": 1}
        if spec.kind == "uniform":
            prior = {r: 1.0 / len(room_ids) for r in room_ids}
            row = _make_row(cmd, spec, labeled, room_ids, source="uniform", prior=prior,
                            rationale="Uniform prior over all rooms.")
        else:
            match = keyword_ground(cmd.command, graph, vocabulary, keyword_table,
                                   floor=config.floor)
            row = _make_row(
                cmd, spec, labeled, room_ids, source="keyword", prior=match.result.room_prior,
                targets=match.result.targets, rationale=match.result.rationale,
                no_keyword_match=match.no_match)
        logger.log({"timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                    "command": cmd.command, "source": row.source, "top1": row.top1,
                    "top2": row.top2, "result": {"room_prior": row.prior,
                                                 "targets": list(row.targets)}})
        return row

    rows: list[CallRow] = []
    for spec in methods:
        for cmd in commands:
            row = run_llm(spec, cmd) if spec.kind == "llm" else run_baseline(spec, cmd)
            rows.append(row)
            say(f"{spec.name:<18} {cmd.id}  {row.source:<8} top1={row.top1:.2f} "
                f"top2={row.top2:.2f}"
                + (f"  latency={row.latency_s:.2f}s" if row.latency_s is not None else "")
                + (f"  passes={row.passes}" if row.passes > 1 else "")
                + (f"  [{row.fallback_reason}]" if row.fallback_reason else ""))

    paths = {
        "calls": run_dir / "calls.jsonl",
        "per_command": run_dir / "per_command.csv",
        "summary": run_dir / "summary.md",
        "failures": run_dir / "failures.md",
    }
    write_per_command_csv(rows, paths["per_command"])
    paths["summary"].write_text(
        render_summary(
            rows, commands, methods, stamp=stamp, labels_path=Path(labels_path),
            commands_count=len(commands), dry_run=dry_run, min_interval_s=min_interval_s,
            max_passes=max_passes, backoff_s=backoff_s),
        encoding="utf-8")
    paths["failures"].write_text(render_failures(rows, methods), encoding="utf-8")
    return E1Result(run_dir, rows, paths)


# --------------------------------------------------------------------------- reports

CSV_COLUMNS = [
    "id", "type", "method", "source", "attempts", "top1", "top2", "constraint_ok", "latency_s",
    "ranked_rooms", "targets", "rationale", "fallback_reason", "passes",
]


def write_per_command_csv(rows: Sequence[CallRow], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for r in rows:
            writer.writerow([
                r.id, r.type, r.method, r.source, r.attempts, f"{r.top1:.4f}", f"{r.top2:.4f}",
                "" if r.constraint_ok is None else int(r.constraint_ok),
                "" if r.latency_s is None else f"{r.latency_s:.4f}",
                " ".join(r.ranked), "; ".join(r.targets), r.rationale,
                r.fallback_reason or "", r.passes,
            ])


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _sec(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _md_table(header: Sequence[str], body: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _method_rows(rows: Sequence[CallRow], method: str) -> list[CallRow]:
    return [r for r in rows if r.method == method]


def render_summary(
    rows: Sequence[CallRow],
    commands: Sequence[E1Command],
    methods: Sequence[MethodSpec],
    *,
    stamp: str,
    labels_path: Path,
    commands_count: int,
    dry_run: bool,
    min_interval_s: float,
    max_passes: int,
    backoff_s: float,
) -> str:
    out: list[str] = ["# E1 grounding experiment: summary", ""]
    if dry_run:
        out += ["**DRY RUN: fake backend, the numbers below say nothing about any LLM.**", ""]
    models = {m.name: sorted({r.model for r in _method_rows(rows, m.name) if r.model})
              for m in methods if m.kind == "llm"}
    out += [
        f"- Run: {stamp}",
        f"- Commands: {commands_count} (labels: `{labels_path}`)",
        f"- Methods: {', '.join(m.name for m in methods)}",
        "- Models: " + ("; ".join(f"{k}: {', '.join(v) or '-'}" for k, v in models.items())
                        or "none"),
        f"- Pacing: calls to one provider start at least {min_interval_s:g} s apart; a command "
        f"whose call ended in a backend error is re-run after a backoff of {backoff_s:g} s "
        f"(doubling), up to {max_passes} passes",
        "- LLM runs did not read or write the cache; latency is the backend latency of the "
        "successful attempt.",
        "",
    ]

    stats = {m.name: aggregate_rows(_method_rows(rows, m.name)) for m in methods}
    n_con = next((s.n_constrained for s in stats.values() if s.n_constrained), 0)
    n_unc = next((s.n_unconstrained for s in stats.values() if s.n_unconstrained), 0)

    out += ["## Overall", ""]
    out.append(_md_table(
        ["Method", "n", "top-1", "top-2", "constraint match", "constraint null",
         "latency mean (s)", "median", "p95", "fallback rows", "invalid output"],
        [[m.name, str(s.n), _pct(s.top1), _pct(s.top2), _pct(s.constraint_match),
          _pct(s.constraint_null), _sec(s.latency_mean), _sec(s.latency_median),
          _sec(s.latency_p95), str(s.fallback_rows),
          f"{s.invalid_output_rows} ({_pct(s.invalid_output_rate)})"]
         for m in methods for s in [stats[m.name]]]))
    out += [
        "",
        f"Constraint match: exact set match with the expected constraint, over the {n_con} "
        f"commands that have one. Constraint null: `room_constraint` is null, over the {n_unc} "
        f"commands without one. Both are shown for the LLM methods only. A command that never "
        f"got an LLM answer counts as a miss in every rate; latency covers answered commands "
        f"only. Keyword-fallback results are never counted as LLM results.",
        "",
    ]

    out += ["## By command type", ""]
    for t in command_types(commands):
        out += [f"### {t}", ""]
        body = []
        for m in methods:
            s = aggregate_rows([r for r in _method_rows(rows, m.name) if r.type == t])
            body.append([m.name, str(s.n), _pct(s.top1), _pct(s.top2), _pct(s.constraint_match),
                         _pct(s.constraint_null), str(s.fallback_rows),
                         f"{s.invalid_output_rows} ({_pct(s.invalid_output_rate)})"])
        out += [_md_table(["Method", "n", "top-1", "top-2", "constraint match",
                           "constraint null", "fallback rows", "invalid output"], body), ""]

    ablation = []
    for provider in PROVIDER_KIND:
        full, names = stats.get(f"{provider}_full"), stats.get(f"{provider}_names_only")
        if full is None or names is None:
            continue
        for label, a, b in [("top-1", full.top1, names.top1), ("top-2", full.top2, names.top2),
                            ("constraint match", full.constraint_match, names.constraint_match),
                            ("constraint null", full.constraint_null, names.constraint_null)]:
            delta = "-" if a is None or b is None else f"{100 * (a - b):+.1f} pp"
            ablation.append([provider, label, _pct(a), _pct(b), delta])
    out += ["## Scene-graph ablation (full minus names only)", ""]
    out += [_md_table(["Provider", "Metric", "full", "names only", "difference"], ablation)
            if ablation else "Both variants of a provider are needed for this table.", ""]

    latency_body = []
    for provider, kind in PROVIDER_KIND.items():
        values = [r.latency_s for m in methods if m.provider == provider
                  for r in _method_rows(rows, m.name) if r.latency_s is not None]
        if not values:
            continue
        used = sorted({r.model for m in methods if m.provider == provider
                       for r in _method_rows(rows, m.name) if r.model})
        latency_body.append([f"{kind} ({provider})", ", ".join(used) or "-", str(len(values)),
                             _sec(_mean(values)), _sec(statistics.median(values)),
                             _sec(percentile(values, 0.95))])
    out += ["## Hosted vs local latency (answered LLM calls, all variants pooled)", ""]
    out += [_md_table(["Kind", "Model", "n", "mean (s)", "median", "p95"], latency_body)
            if latency_body else "No LLM answers.",
            "",
            "Hosted latency includes the network; local latency depends on the machine.", ""]

    out += ["## Commands without an LLM answer", ""]
    listed = False
    for m in methods:
        if m.kind != "llm":
            continue
        missing = [r for r in _method_rows(rows, m.name) if r.no_llm_answer]
        if missing:
            listed = True
            items = ", ".join(f"{r.id} ({r.fallback_reason}, {r.passes} pass"
                              f"{'es' if r.passes != 1 else ''})" for r in missing)
            out.append(f"- **{m.name}**: {items}")
    if not listed:
        out.append("None: every LLM command got an answer.")
    out += [
        "",
        "## Scoring",
        "",
        "Rooms are ranked by `room_prior`, highest first. top-1 hit: the top room is labeled "
        "plausible; top-2 hit: at least one of the top two is. Tied rooms at the cut-off are "
        "scored with the expected value under random tie-breaking, so the uniform baseline is "
        "well defined (for example 2 labeled rooms of 6 give top-1 = 2/6).",
        "",
    ]
    return "\n".join(out)


def render_failures(rows: Sequence[CallRow], methods: Sequence[MethodSpec]) -> str:
    out = ["# E1 top-1 misses", "",
           "Every command and method whose top-1 score is below 1 (a fractional score is a tie "
           "at the cut-off). For the report's failure analysis.", ""]
    for m in methods:
        misses = [r for r in _method_rows(rows, m.name) if r.top1 < 1.0 - 1e-12]
        out += [f"## {m.name} ({len(misses)} of {len(_method_rows(rows, m.name))})", ""]
        if not misses:
            out += ["No top-1 misses.", ""]
        for r in misses:
            out += [f"### {r.id} ({r.type}): {r.command}",
                    f"- labeled: {', '.join(r.labeled)}"]
            if r.no_llm_answer:
                out.append(f"- no LLM answer: {r.fallback_reason} after {r.passes} pass(es); "
                           f"counted as a miss")
            else:
                ranked = " > ".join(f"{room} {r.prior[room]:.3f}" for room in r.ranked)
                out += [f"- ranked: {ranked}", f"- top-1 score: {r.top1:.2f}",
                        f"- rationale: {r.rationale or '-'}"]
                if r.constraint_ok is False:
                    expected = "null" if r.expected_constraint is None \
                        else ", ".join(r.expected_constraint)
                    got = "null" if r.room_constraint is None else ", ".join(r.room_constraint)
                    out.append(f"- constraint: expected {expected}; got {got}")
            out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- CLI

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lang_grounding.e1", description="The E1 grounding experiment.")
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="run the experiment and write results/e1/<timestamp>/")
    run.add_argument("--labels", default=str(DEFAULT_LABELS_PATH),
                     help="label CSV (default: data/e1_labels_final.csv)")
    run.add_argument("--commands", default=str(DEFAULT_COMMANDS_PATH),
                     help="E1 command file (default: data/e1_commands.json)")
    run.add_argument("--methods", help=f"comma-separated subset of: {', '.join(ALL_METHODS)} "
                                       f"(default: all)")
    run.add_argument("--min-interval-s", type=float, default=6.0,
                     help="minimum seconds between call starts to one provider (default 6)")
    run.add_argument("--max-passes", type=int, default=3,
                     help="passes per command after backend-error fallbacks (default 3)")
    run.add_argument("--backoff-s", type=float, default=30.0,
                     help="wait before a re-run, doubling each pass (default 30)")
    run.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                     help="parent of the timestamped result folder (default: results/e1)")
    run.add_argument("--dry-run", action="store_true",
                     help="use the fake backend for the LLM methods, no waiting, no network")
    run.add_argument("--config", help="path to a grounding.json (default: configs/)")
    run.add_argument("--env-file", help="env file to read first (default: .env in the repo)")
    run.add_argument("--graph", help="scene graph JSON (default: from the config)")
    run.add_argument("--vocabulary", help="vocabulary JSON (default: from the config)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 done, 1 the label file failed validation, 2 setup or option errors."""
    args = _build_parser().parse_args(argv)
    try:
        config = load_config(args.config, env_file=args.env_file)
        graph = load_scene_graph(args.graph or config.resolve(config.paths.scene_graph))
        vocabulary = load_vocabulary(args.vocabulary or config.resolve(config.paths.vocabulary))
        commands = load_e1_commands(args.commands)
        methods = parse_methods(
            [x.strip() for x in args.methods.split(",") if x.strip()] if args.methods else None)
        prompts = PromptBuilder.from_config(config)
        table = load_keyword_table(config.resolve(config.paths.keyword_table))
        backends: dict[str, Backend] = {}
        for m in methods:
            if m.kind == "llm" and m.provider not in backends:
                backends[m.provider] = (
                    FakeBackend(model=f"fake-{m.provider}") if args.dry_run
                    else create_backend(m.provider, config))
        result = run_experiment(
            config=config, graph=graph, vocabulary=vocabulary, commands=commands,
            labels_path=args.labels, methods=methods, out_dir=args.out_dir, backends=backends,
            prompts=prompts, keyword_table=table,
            min_interval_s=0.0 if args.dry_run else args.min_interval_s,
            max_passes=args.max_passes,
            backoff_s=0.0 if args.dry_run else args.backoff_s,
            dry_run=args.dry_run, progress=lambda msg: print(msg, flush=True))
    except LabelGateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:  # options, config, scene graph, vocabulary, command file
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print()
    print(f"Results: {result.run_dir}")
    for name, path in result.paths.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
