"""JSONL log of grounding calls (D-114): one JSON object per line. No ROS imports.

Secrets are never written: the API key is not part of any record, and as a safeguard any string
equal to a secret value found in a record (the GEMINI_API_KEY value, by default) is replaced.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lang_grounding.config import GEMINI_API_KEY_ENV

REDACTED = "[REDACTED]"


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, Mapping):
        return {k: _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, secrets) for v in value]
    return value


class GroundingLogger:
    def __init__(self, path: str | Path, secrets: Sequence[str] | None = None) -> None:
        self.path = Path(path)
        self._secrets = None if secrets is None else [s for s in secrets if s]

    def log(self, record: Mapping[str, Any]) -> None:
        secrets = self._secrets
        if secrets is None:  # read the environment at write time, so a later export is covered
            secrets = [s for s in (os.environ.get(GEMINI_API_KEY_ENV),) if s]
        line = json.dumps(_redact(record, secrets), ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
