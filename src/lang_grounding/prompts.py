"""Prompt builder (D-110): system template and few-shot examples come from configs/prompts/.

The system template must contain the placeholders {scene_graph}, {vocabulary} and {examples}.
Few-shot examples are rendered into the system prompt. The user prompt carries the command.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lang_grounding.config import ConfigError, GroundingConfig
from lang_grounding.scene_graph import SceneGraph, render_for_prompt

_PLACEHOLDER_RE = re.compile(r"\{(scene_graph|vocabulary|examples)\}")
REQUIRED_PLACEHOLDERS = ("{scene_graph}", "{vocabulary}", "{examples}")


@dataclass(frozen=True)
class FewShotExample:
    command: str
    response: dict[str, Any]


@dataclass(frozen=True)
class Prompts:
    system: str
    user: str


def load_fewshot(path: str | Path) -> list[FewShotExample]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read few-shot file {p}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{p} is not valid JSON: {exc}") from exc
    items = data.get("examples") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ConfigError(f'{p} must be a JSON object with an "examples" list')
    examples = []
    for i, item in enumerate(items):
        if (not isinstance(item, dict)
                or not isinstance(item.get("command"), str) or not item["command"].strip()
                or not isinstance(item.get("response"), dict)):
            raise ConfigError(
                f'{p}: example {i} needs a non-empty "command" string and a "response" object')
        examples.append(FewShotExample(item["command"], item["response"]))
    return examples


class PromptBuilder:
    def __init__(self, system_template: str, examples: Sequence[FewShotExample] = ()) -> None:
        missing = [p for p in REQUIRED_PLACEHOLDERS if p not in system_template]
        if missing:
            raise ConfigError(f"system prompt template is missing placeholder(s): {missing}")
        self.system_template = system_template
        self.examples = tuple(examples)

    @classmethod
    def from_files(cls, system_path: str | Path, fewshot_path: str | Path) -> PromptBuilder:
        p = Path(system_path)
        try:
            template = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read system prompt {p}: {exc.strerror or exc}") from exc
        return cls(template, load_fewshot(fewshot_path))

    @classmethod
    def from_config(cls, config: GroundingConfig) -> PromptBuilder:
        return cls.from_files(
            config.resolve(config.paths.system_prompt), config.resolve(config.paths.fewshot))

    def render_examples(self) -> str:
        if not self.examples:
            return "(none)"
        blocks = [
            f"Example {i}\nCommand: {ex.command}\n"
            f"Response: {json.dumps(ex.response, ensure_ascii=False)}"
            for i, ex in enumerate(self.examples, start=1)
        ]
        return "\n\n".join(blocks)

    def build(self, command: str, graph: SceneGraph, vocabulary: Sequence[str]) -> Prompts:
        values = {
            "scene_graph": render_for_prompt(graph),
            "vocabulary": ", ".join(vocabulary),
            "examples": self.render_examples(),
        }
        system = _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], self.system_template)
        return Prompts(system=system, user=f"Command: {command.strip()}")


def build_retry_prompt(user_prompt: str, errors: Sequence[str]) -> str:
    """The original user prompt with the validator's errors appended (D-014)."""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        f"{user_prompt}\n\n"
        f"Your previous response was rejected for these reasons:\n{lines}\n"
        f"Return a corrected JSON object that fixes every problem listed."
    )
