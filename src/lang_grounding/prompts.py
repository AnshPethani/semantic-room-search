"""Prompt builder (D-110, D-116): system template and few-shot examples from configs/prompts/.

The system template must contain the placeholders {scene_graph} and {vocabulary}. It may also
contain {examples}; if it does not, the few-shot examples are appended to the system prompt
under an "## Examples" heading. fewshot.json is a JSON list of {"command", "response"} objects,
or an object with an "examples" list of them. The user prompt carries the command.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lang_grounding.config import ConfigError, GroundingConfig
from lang_grounding.scene_graph import SceneGraph, render_for_prompt, render_names_only

SCENE_GRAPH_STYLES = ("full", "names_only")  # "names_only" is the E1 ablation (D-124)

_PLACEHOLDER_RE = re.compile(r"\{(scene_graph|vocabulary|examples)\}")
REQUIRED_PLACEHOLDERS = ("{scene_graph}", "{vocabulary}")
EXAMPLES_PLACEHOLDER = "{examples}"
EXAMPLES_HEADING = (
    "## Examples\n"
    "Each example shows a command and the complete JSON response expected for it."
)


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
    # Two layouts are accepted: a bare list, or an object with an "examples" list.
    items = data.get("examples") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ConfigError(
            f'{p} must be a JSON list of {{"command", "response"}} objects, '
            f'or an object with an "examples" list of them')
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
    def __init__(
        self,
        system_template: str,
        examples: Sequence[FewShotExample] = (),
        scene_graph_style: str = "full",
    ) -> None:
        missing = [p for p in REQUIRED_PLACEHOLDERS if p not in system_template]
        if missing:
            raise ConfigError(f"system prompt template is missing placeholder(s): {missing}")
        if scene_graph_style not in SCENE_GRAPH_STYLES:
            raise ConfigError(
                f"unknown scene graph style {scene_graph_style!r}; use one of {SCENE_GRAPH_STYLES}")
        self.system_template = system_template
        self.examples = tuple(examples)
        self.scene_graph_style = scene_graph_style

    def with_scene_graph_style(self, style: str) -> PromptBuilder:
        """A copy that renders the building description in the given style."""
        return PromptBuilder(self.system_template, self.examples, style)

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
        render = render_names_only if self.scene_graph_style == "names_only" else render_for_prompt
        values = {
            "scene_graph": render(graph),
            "vocabulary": ", ".join(vocabulary),
            "examples": self.render_examples(),
        }
        system = _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], self.system_template)
        if EXAMPLES_PLACEHOLDER not in self.system_template and self.examples:
            system = f"{system.rstrip()}\n\n{EXAMPLES_HEADING}\n\n{self.render_examples()}\n"
        return Prompts(system=system, user=f"Command: {command.strip()}")


def build_retry_prompt(user_prompt: str, errors: Sequence[str]) -> str:
    """The original user prompt with the validator's errors appended (D-014)."""
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        f"{user_prompt}\n\n"
        f"Your previous response was rejected for these reasons:\n{lines}\n"
        f"Return a corrected JSON object that fixes every problem listed."
    )
