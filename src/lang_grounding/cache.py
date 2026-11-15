"""On-disk cache of validated LLM grounding results (D-113). No ROS imports.

Only results that came from a validated LLM response are stored; keyword-fallback results never
are (the caller decides, see ground.py). One JSON file per key, written atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from lang_grounding.grounding_output import GroundingResult
from lang_grounding.scene_graph import SceneGraph

_KEY_VERSION = 1


def normalize_command(command: str) -> str:
    """Whitespace collapsed and case folded, so trivially different spellings share a key."""
    return " ".join(command.split()).casefold()


def make_cache_key(
    *,
    command: str,
    graph: SceneGraph,
    vocabulary: Sequence[str],
    model: str,
    system_prompt: str,
    floor: float,
) -> str:
    """SHA-256 over everything that can change a grounding result.

    `system_prompt` is the fully rendered system prompt, so it already contains the template,
    the few-shot examples, the scene graph text and the vocabulary; editing any of them changes
    the key. The scene graph is also hashed on its own, without `viewpoints` (they never reach
    the prompt, so regenerating them must not invalidate cached answers).
    """
    graph_data = graph.model_dump(mode="json", exclude={"rooms": {"__all__": {"viewpoints"}}})
    payload = {
        "key_version": _KEY_VERSION,
        "command": normalize_command(command),
        "graph": graph_data,
        "vocabulary": list(vocabulary),
        "model": model,
        "system_prompt": system_prompt,
        "floor": floor,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GroundingCache:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> GroundingResult | None:
        """The cached result, or None if absent or unreadable (a corrupt file is a miss)."""
        try:
            data = json.loads(self._path(key).read_text(encoding="utf-8"))
            return GroundingResult.model_validate(data["result"])
        except (OSError, ValueError, KeyError, TypeError, ValidationError):
            return None

    def put(self, key: str, result: GroundingResult, *, command: str, model: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "command": command,
            "model": model,
            "created": time.time(),
            "result": result.model_dump(mode="json"),
        }
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path(key))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
