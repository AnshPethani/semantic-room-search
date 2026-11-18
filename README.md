# semantic-room-search

LLM-grounded semantic object search in a known floorplan (CSC 591 Advanced Robotics).

The `lang_grounding` package turns a natural-language command into target objects and a
probability prior over rooms. It is pure Python with no ROS dependency; ROS 2 wrappers will live
in `ros/`.

## Setup

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in GEMINI_API_KEY and GEMINI_MODEL
```

`.env` at the repository root is read automatically by the CLI and by anything that loads the
configuration (`load_config`), so there is no need to `export` the variables. A variable that
is already set in the shell wins over the file. `.env` is gitignored; never commit it. Use
`--env-file <path>` on the CLI to read a different file (a relative path is relative to the
repository root).

## Try it

```
# offline, no key needed
python -m lang_grounding.ground "find the banana" --backend fake --no-log

# Gemini, using the key and model from .env
python -m lang_grounding.ground "find the banana" --backend gemini --no-log
```

## ROS 2

`ros/semantic_msgs` (messages and the `/ground_command` service type) and `ros/lang_grounding_ros`
(a thin service node around this library) are built in the separate pixi environment, not in the
`.venv`. Setup, run commands and parameters: [docs/ROS.md](docs/ROS.md).

## Tests and lint

```
pytest
ruff check .
```

Design decisions are tracked in [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).
