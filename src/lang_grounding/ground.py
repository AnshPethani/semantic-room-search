"""The grounding loop (D-111): cache, backend, validation, one retry, keyword fallback.

    python -m lang_grounding.ground "find the banana" --backend fake

Pure Python, no ROS imports.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from lang_grounding.backends import Backend, BackendError, create_backend
from lang_grounding.cache import GroundingCache, make_cache_key
from lang_grounding.config import GroundingConfig, load_config
from lang_grounding.grounding_log import GroundingLogger
from lang_grounding.grounding_output import (
    DEFAULT_FLOOR,
    GroundingResult,
    build_output_schema,
    check_vocabulary,
    load_vocabulary,
    validate_grounding,
)
from lang_grounding.keyword_fallback import KeywordTable, keyword_ground, load_keyword_table
from lang_grounding.prompts import PromptBuilder, build_retry_prompt
from lang_grounding.scene_graph import SceneGraph, load_scene_graph

MAX_ATTEMPTS = 2  # first try plus one retry (D-014)

Source = Literal["llm", "cache", "fallback"]


@dataclass(frozen=True)
class GroundOutcome:
    """Result of one ground() call.

    source: "llm" (validated backend answer), "cache", or "fallback" (keyword table).
    attempts: backend calls made (0 for a cache hit, at most 2).
    latency_s: wall-clock seconds for the whole call, retries included.
    model: the backend's model name (also for cache and fallback results).
    errors: backend errors and validation errors seen, each prefixed with its attempt number.
    no_keyword_match: fallback only; True if no keyword matched (uniform prior, all targets).
    fallback_reason: fallback only; "backend_error" if the last thing that happened was a
        backend error (timeout, rate limit, network, malformed response), "invalid_output" if
        the backend answered twice but the answer was invalid both times (D-123).
    backend_latency_s: llm only; the backend latency of the successful attempt, without the
        failed attempt or the retry overhead (D-123).
    """

    command: str
    result: GroundingResult
    source: Source
    attempts: int
    latency_s: float
    model: str
    errors: tuple[str, ...] = ()
    no_keyword_match: bool = False
    fallback_reason: str | None = None
    backend_latency_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "source": self.source,
            "attempts": self.attempts,
            "latency_s": round(self.latency_s, 4),
            "model": self.model,
            "errors": list(self.errors),
            "no_keyword_match": self.no_keyword_match,
            "fallback_reason": self.fallback_reason,
            "backend_latency_s": (
                None if self.backend_latency_s is None else round(self.backend_latency_s, 4)),
            "result": self.result.model_dump(mode="json"),
        }


def _parse_json(text: str) -> tuple[Any, str | None]:
    """Parse a response; a Markdown code fence around the JSON is tolerated."""
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    try:
        return json.loads(body), None
    except json.JSONDecodeError as exc:
        return None, f"response is not valid JSON: {exc}"


def ground(
    command: str,
    graph: SceneGraph,
    vocabulary: Sequence[str],
    backend: Backend,
    cache: GroundingCache | None = None,
    logger: GroundingLogger | None = None,
    *,
    prompts: PromptBuilder | None = None,
    keyword_table: KeywordTable | None = None,
    floor: float = DEFAULT_FLOOR,
) -> GroundOutcome:
    """Ground a command: cache lookup, backend call, validation, one retry, keyword fallback.

    `prompts` and `keyword_table` default to the files named in configs/grounding.json. Only
    validated backend results are cached; fallback results never are. Backend errors (timeout,
    rate limit, malformed response, ...) go straight to the fallback without a retry.
    """
    if not command or not command.strip():
        raise ValueError("command must not be empty")
    vocab = check_vocabulary(vocabulary)
    start = time.perf_counter()

    if prompts is None:
        prompts = PromptBuilder.from_config(load_config())
    prompt = prompts.build(command, graph, vocab)
    key = make_cache_key(
        command=command, graph=graph, vocabulary=vocab, model=backend.model,
        system_prompt=prompt.system, floor=floor)

    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            outcome = GroundOutcome(
                command=command, result=cached, source="cache", attempts=0,
                latency_s=time.perf_counter() - start, model=backend.model)
            _log(logger, outcome, raw_responses=[], validation=[], backend_errors=[],
                 backend_latencies=[])
            return outcome

    schema = build_output_schema(graph, vocab)
    errors: list[str] = []
    raw_responses: list[str] = []
    validation: list[dict[str, Any]] = []
    backend_errors: list[str] = []
    backend_latencies: list[float] = []
    result: GroundingResult | None = None
    attempts = 0
    user_prompt = prompt.user

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            response = backend.generate(prompt.system, user_prompt, schema)
        except BackendError as exc:
            message = f"{type(exc).__name__}: {exc}"
            backend_errors.append(message)
            errors.append(f"attempt {attempt}: backend error: {message}")
            break
        raw_responses.append(response.text)
        backend_latencies.append(response.latency_s)

        data, parse_error = _parse_json(response.text)
        verdict = [parse_error] if parse_error else validate_grounding(
            data, graph, vocab, floor=floor)
        if isinstance(verdict, GroundingResult):
            validation.append({"attempt": attempt, "errors": []})
            result = verdict
            break
        validation.append({"attempt": attempt, "errors": list(verdict)})
        errors.extend(f"attempt {attempt}: {e}" for e in verdict)
        if attempt < MAX_ATTEMPTS:
            user_prompt = build_retry_prompt(prompt.user, verdict)

    if result is not None:
        if cache is not None:
            cache.put(key, result, command=command, model=backend.model)
        outcome = GroundOutcome(
            command=command, result=result, source="llm", attempts=attempts,
            latency_s=time.perf_counter() - start, model=backend.model, errors=tuple(errors),
            backend_latency_s=backend_latencies[-1])
    else:
        match = keyword_ground(command, graph, vocab, keyword_table, floor=floor)
        outcome = GroundOutcome(
            command=command, result=match.result, source="fallback", attempts=attempts,
            latency_s=time.perf_counter() - start, model=backend.model,
            errors=tuple(errors), no_keyword_match=match.no_match,
            fallback_reason="backend_error" if backend_errors else "invalid_output")

    _log(logger, outcome, raw_responses=raw_responses, validation=validation,
         backend_errors=backend_errors, backend_latencies=backend_latencies)
    return outcome


def _log(
    logger: GroundingLogger | None,
    outcome: GroundOutcome,
    *,
    raw_responses: list[str],
    validation: list[dict[str, Any]],
    backend_errors: list[str],
    backend_latencies: list[float],
) -> None:
    if logger is None:
        return
    logger.log({
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "command": outcome.command,
        "model": outcome.model,
        "cache_hit": outcome.source == "cache",
        "source": outcome.source,
        "attempts": outcome.attempts,
        "latency_s": round(outcome.latency_s, 4),
        "backend_latencies_s": [round(x, 4) for x in backend_latencies],
        "raw_responses": raw_responses,
        "validation_errors": validation,
        "backend_errors": backend_errors,
        "no_keyword_match": outcome.no_keyword_match,
        "fallback_reason": outcome.fallback_reason,
        "backend_latency_s": (
            None if outcome.backend_latency_s is None else round(outcome.backend_latency_s, 4)),
        "result": outcome.result.model_dump(mode="json"),
    })


# --------------------------------------------------------------------------- CLI

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lang_grounding.ground",
        description="Ground a natural-language command into targets and a room prior.")
    parser.add_argument("command", help="the command to ground, in quotes")
    parser.add_argument("--backend", choices=["gemini", "ollama", "fake"], default="fake")
    parser.add_argument("--config", help="path to a grounding.json (default: configs/)")
    parser.add_argument(
        "--env-file",
        help="env file to read first (default: .env at the repository root; a relative path "
             "is relative to the repository root; variables already set win)")
    parser.add_argument("--graph", help="scene graph JSON (default: from the config)")
    parser.add_argument("--vocabulary", help="vocabulary JSON (default: from the config)")
    parser.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    parser.add_argument("--no-log", action="store_true", help="do not write the JSONL log")
    return parser


def _setup(args: argparse.Namespace) -> dict[str, Any]:
    # load_config reads the env file first, before anything else is set up (D-120)
    config: GroundingConfig = load_config(args.config, env_file=args.env_file)
    return {
        "config": config,
        "graph": load_scene_graph(args.graph or config.resolve(config.paths.scene_graph)),
        "vocabulary": load_vocabulary(
            args.vocabulary or config.resolve(config.paths.vocabulary)),
        "backend": create_backend(args.backend, config),
        "prompts": PromptBuilder.from_config(config),
        "table": load_keyword_table(config.resolve(config.paths.keyword_table)),
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        s = _setup(args)
        config: GroundingConfig = s["config"]
        cache = None if args.no_cache else GroundingCache(config.resolve(config.paths.cache_dir))
        logger = None if args.no_log else GroundingLogger(config.resolve(config.paths.log_path))
        outcome = ground(
            args.command, s["graph"], s["vocabulary"], s["backend"], cache, logger,
            prompts=s["prompts"], keyword_table=s["table"], floor=config.floor)
    except ValueError as exc:  # config, scene graph, vocabulary and empty-command errors
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(outcome.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
