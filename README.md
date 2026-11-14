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

## Tests and lint

```
pytest
ruff check .
```

Design decisions are tracked in [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).
