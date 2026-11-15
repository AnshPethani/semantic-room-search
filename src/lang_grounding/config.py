"""Grounding settings, loaded from configs/grounding.json (D-105). No secrets live here."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "grounding.json"

# Environment variables (values are never written to files or logs).
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_MODEL_ENV = "GEMINI_MODEL"


class ConfigError(ValueError):
    """A configuration file or setting is missing or unusable."""


class GeminiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None  # null here; set GEMINI_MODEL or fill this in (copy the ID from AI Studio)
    timeout_s: float
    temperature: float


class OllamaSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    host: str
    timeout_s: float
    temperature: float


class PathSettings(BaseModel):
    """Paths; relative ones are resolved against the repository root."""

    model_config = ConfigDict(extra="forbid")

    scene_graph: str
    vocabulary: str
    keyword_table: str
    system_prompt: str
    fewshot: str
    cache_dir: str
    log_path: str


class GroundingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gemini: GeminiSettings
    ollama: OllamaSettings
    floor: float
    paths: PathSettings

    def resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else REPO_ROOT / path


def load_config(
    path: str | Path | None = None, *, env_file: str | Path | None = None
) -> GroundingConfig:
    """Load the settings. Also loads the .env file first (D-120), so keys in it are visible to
    the backends; variables already set in the environment win. `env_file` overrides the
    default `.env` at the repository root."""
    from lang_grounding.env import load_env_file  # here, not at the top: env imports this module

    load_env_file(env_file)
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {p}: {exc.strerror or exc}") from exc
    try:
        return GroundingConfig.model_validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{p} is not valid JSON: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"invalid config {p}: {problems}") from exc
