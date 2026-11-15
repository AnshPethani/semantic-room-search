"""Keyword fallback and E1 keyword baseline (D-112). No LLM, no ROS; usable on its own.

    match = keyword_ground("find the banana", graph, vocabulary)   # table from configs/
    match.result   # GroundingResult (validated, normalized, floored)
    match.no_match # True when no keyword matched (uniform prior, whole vocabulary)
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from lang_grounding.config import DEFAULT_CONFIG_PATH, ConfigError
from lang_grounding.grounding_output import (
    DEFAULT_FLOOR,
    GroundingResult,
    check_vocabulary,
    validate_grounding,
)
from lang_grounding.scene_graph import SceneGraph

DEFAULT_KEYWORD_TABLE_PATH = DEFAULT_CONFIG_PATH.parent / "keyword_rooms.json"


class KeywordEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str]
    targets: list[str]
    room_prior: dict[str, float]


class KeywordTable(BaseModel):
    model_config = ConfigDict(extra="ignore")  # "description" and similar notes are allowed

    entries: list[KeywordEntry]


@dataclass(frozen=True)
class KeywordMatch:
    result: GroundingResult
    matched: tuple[str, ...]  # the keywords found in the command, in order of appearance
    no_match: bool


def load_keyword_table(path: str | Path | None = None) -> KeywordTable:
    p = Path(path) if path is not None else DEFAULT_KEYWORD_TABLE_PATH
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read keyword table {p}: {exc.strerror or exc}") from exc
    try:
        table = KeywordTable.model_validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{p} is not valid JSON: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"invalid keyword table {p}: {problems}") from exc
    for i, entry in enumerate(table.entries):
        if not entry.keywords or any(not k.strip() for k in entry.keywords):
            raise ConfigError(f"keyword table {p}: entry {i} needs non-empty keywords")
        if not entry.targets:
            raise ConfigError(f"keyword table {p}: entry {i} needs at least one target")
    return table


def check_keyword_table(
    table: KeywordTable,
    graph: SceneGraph,
    vocabulary: Sequence[str],
    *,
    floor: float = DEFAULT_FLOOR,
) -> list[str]:
    """Problems found by running every entry through the validator (empty list means fine)."""
    problems = []
    for entry in table.entries:
        outcome = validate_grounding(
            {"targets": entry.targets, "room_prior": entry.room_prior, "room_constraint": None},
            graph, vocabulary, floor=floor)
        if isinstance(outcome, list):
            label = "/".join(entry.keywords)
            problems.extend(f"entry '{label}': {e}" for e in outcome)
    return problems


def _first_match(keywords: Sequence[str], text: str) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for kw in keywords:
        pattern = r"(?<![a-z0-9])" + re.escape(kw.lower().strip()) + r"(?:s|es)?(?![a-z0-9])"
        m = re.search(pattern, text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), kw)
    return best


def keyword_ground(
    command: str,
    graph: SceneGraph,
    vocabulary: Sequence[str],
    table: KeywordTable | None = None,
    *,
    floor: float = DEFAULT_FLOOR,
) -> KeywordMatch:
    """Ground a command with the keyword table only.

    Every entry with a keyword in the command matches. Targets are the matched entries' targets
    (restricted to the vocabulary, in order of appearance in the command, no duplicates); the
    room prior is the average of the matched priors. With no match: the whole vocabulary as
    targets and a uniform prior. An entry whose own prior is invalid raises ConfigError.
    """
    vocab = check_vocabulary(vocabulary)
    table = table if table is not None else load_keyword_table()
    text = " ".join(command.split()).lower()
    room_ids = graph.room_ids

    hits = []
    for index, entry in enumerate(table.entries):
        targets = [t for t in entry.targets if t in vocab]
        found = _first_match(entry.keywords, text) if targets else None
        if found is not None:
            hits.append((found[0], index, found[1], entry, targets))
    hits.sort(key=lambda h: (h[0], h[1]))

    if not hits:
        raw = {
            "targets": list(vocab),
            "room_prior": {rid: 1.0 / len(room_ids) for rid in room_ids},
            "room_constraint": None,
            "rationale": "Keyword fallback: no keyword matched; uniform prior over all rooms.",
        }
        return KeywordMatch(_validated(raw, graph, vocab, floor), (), True)

    targets: list[str] = []
    for _, _, _, _, entry_targets in hits:
        targets.extend(t for t in entry_targets if t not in targets)
    prior = {}
    for rid in room_ids:
        values = [h[3].room_prior.get(rid) for h in hits]
        if any(v is None for v in values):
            label = "/".join(h[3].keywords[0] for h in hits)
            raise ConfigError(f"keyword table entry for '{label}' has no prior for room {rid}")
        prior[rid] = sum(values) / len(values)
    matched = tuple(h[2] for h in hits)
    raw = {
        "targets": targets,
        "room_prior": prior,
        "room_constraint": None,
        "rationale": f"Keyword fallback matched: {', '.join(matched)}."[:300],
    }
    return KeywordMatch(_validated(raw, graph, vocab, floor), matched, False)


def _validated(raw: dict, graph: SceneGraph, vocab: tuple[str, ...], floor: float):
    outcome = validate_grounding(raw, graph, vocab, floor=floor)
    if isinstance(outcome, list):
        raise ConfigError(f"keyword table produced an invalid result: {'; '.join(outcome)}")
    return outcome
