"""Minimal .env loader (D-120). Standard library only; no ROS imports.

Supported lines: `NAME=value`, with an optional `export ` prefix; blank lines and `#` comments
are ignored. Values may be wrapped in matching single or double quotes (removed). There is no
variable expansion and no escape processing. An unquoted value ends at ` #` (whitespace then
a hash), which starts an inline comment.

Variables that are already set in the environment are never overridden. A missing file is not
an error. A malformed line raises ConfigError naming the file and line number; the message
never contains the line, the variable name or the value, because a malformed line may be a
secret pasted without its name.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

from lang_grounding.config import REPO_ROOT, ConfigError

DEFAULT_ENV_PATH = REPO_ROOT / ".env"

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INLINE_COMMENT_RE = re.compile(r"\s+#")


class _BadLine(ValueError):
    """Internal: why a line is malformed (never includes the line itself)."""


def resolve_env_path(path: str | Path | None = None) -> Path:
    """`.env` at the repository root by default; a relative path is relative to the root too."""
    if path is None:
        return DEFAULT_ENV_PATH
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _parse_line(raw: str) -> tuple[str, str] | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export") and len(line) > 6 and line[6] in " \t":
        line = line[6:].lstrip()
    name, sep, value = line.partition("=")
    if not sep:
        raise _BadLine("not a NAME=value assignment")
    name = name.strip()
    if not _NAME_RE.match(name):
        raise _BadLine("invalid variable name")
    value = value.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end == -1:
            raise _BadLine("unterminated quote")
        rest = value[end + 1:].strip()
        if rest and not rest.startswith("#"):
            raise _BadLine("unexpected text after the closing quote")
        return name, value[1:end]
    return name, _INLINE_COMMENT_RE.split(value, maxsplit=1)[0].strip()


def load_env_file(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load NAME=value pairs from a .env file into the environment.

    `path` defaults to `.env` at the repository root. The whole file is parsed before anything
    is set, so a malformed file changes nothing. `environ` is for tests; it defaults to
    os.environ.
    """
    target = os.environ if environ is None else environ
    p = resolve_env_path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return
    except UnicodeDecodeError:
        raise ConfigError(f"env file {p} is not valid UTF-8 text") from None
    except OSError as exc:
        raise ConfigError(f"cannot read env file {p}: {exc.strerror or exc}") from exc

    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        try:
            parsed = _parse_line(raw)
        except _BadLine as exc:
            raise ConfigError(f"{p}: line {lineno}: {exc}") from None
        if parsed is not None:
            values[parsed[0]] = parsed[1]  # a later line for the same name wins within the file

    for name, value in values.items():
        if name not in target:
            target[name] = value
