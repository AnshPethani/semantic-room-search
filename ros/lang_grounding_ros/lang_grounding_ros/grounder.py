"""Builds the grounding handler from the lang_grounding library, once at node start (D-129).

Imports the library (not rclpy), so it runs in the repo's .venv too. Nothing here is grounding
logic: it loads the files, creates the backend, cache and logger, and hands `ground()` to the
handler. The scene graph, vocabulary, config, prompts and keyword table are loaded once, not per
call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lang_grounding.backends import create_backend
from lang_grounding.cache import GroundingCache
from lang_grounding.config import REPO_ROOT, load_config
from lang_grounding.ground import ground
from lang_grounding.grounding_log import GroundingLogger
from lang_grounding.grounding_output import load_vocabulary
from lang_grounding.keyword_fallback import load_keyword_table
from lang_grounding.prompts import PromptBuilder
from lang_grounding.scene_graph import load_scene_graph

from .handler import GroundingHandler


@dataclass(frozen=True)
class GrounderSetup:
    handler: GroundingHandler
    model: str
    summary: str
    notes: tuple[str, ...]  # warnings to show at start-up


def _path(value: str | Path | None) -> Path | None:
    """A parameter value as a path: empty means "use the default", relative means relative to
    the repository root (as in D-105)."""
    if value is None or str(value) == "":
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def build_handler(
    *,
    scene_graph_file: str = "",
    vocabulary_file: str = "",
    config_file: str = "",
    env_file: str = "",
    log_dir: str = "",
    timeout_s: float = 20.0,
    backend: str = "gemini",
    cache_dir: str | Path | None = None,
    max_workers: int = 4,
) -> GrounderSetup:
    """Load everything once and return the handler. Empty strings select the defaults of
    configs/grounding.json. Setup problems raise ValueError subclasses (ConfigError,
    SceneGraphError, VocabularyError), which the node reports and exits on."""
    config = load_config(_path(config_file), env_file=_path(env_file))
    graph = load_scene_graph(_path(scene_graph_file) or config.resolve(config.paths.scene_graph))
    vocabulary = load_vocabulary(_path(vocabulary_file) or config.resolve(config.paths.vocabulary))
    backend_obj = create_backend(backend, config)
    prompts = PromptBuilder.from_config(config)
    table = load_keyword_table(config.resolve(config.paths.keyword_table))
    cache = GroundingCache(_path(cache_dir) or config.resolve(config.paths.cache_dir))
    log_base = _path(log_dir)
    logger = GroundingLogger(
        log_base / "grounding.jsonl" if log_base else config.resolve(config.paths.log_path))

    def ground_fn(command: str) -> dict[str, Any]:
        return ground(
            command, graph, vocabulary, backend_obj, cache, logger,
            prompts=prompts, keyword_table=table, floor=config.floor).to_dict()

    notes = []
    backend_timeout = {"gemini": config.gemini.timeout_s,
                       "ollama": config.ollama.timeout_s}.get(backend)
    if backend_timeout is not None and backend_timeout > timeout_s:
        notes.append(
            f"the {backend} backend timeout ({backend_timeout:g} s) is longer than the node "
            f"timeout ({timeout_s:g} s): a call that times out keeps running in the background "
            f"until the backend gives up")
    return GrounderSetup(
        handler=GroundingHandler(ground_fn, timeout_s=timeout_s, max_workers=max_workers),
        model=backend_obj.model,
        summary=(f"grounding ready: backend={backend} model={backend_obj.model} "
                 f"rooms={len(graph.rooms)} classes={len(vocabulary)} timeout={timeout_s:g}s"),
        notes=tuple(notes))
