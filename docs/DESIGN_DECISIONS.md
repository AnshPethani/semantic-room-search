# Design Decisions Log

Project: LLM-Grounded Semantic Object Search in a Known Floorplan (CSC 591 Advanced Robotics)
Scope: Ansh's part (LLM grounding, scene graph, detector node) and the interfaces shared with Kristika.

**How to use this file.** Every design decision gets an entry, whether it was made in chat or in Claude Code. Claude Code should append new entries here whenever it makes or changes a design choice. Status is one of: `Agreed`, `Proposed` (needs Kristika's confirmation), `Open` (not decided), `Superseded`.

Entry format: ID, date, status, decision, why, alternatives considered.

---

## Phase 0: Alignment

### D-001 Floorplan
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** Use the team's floorplan screenshot (rooms E, K, LR, D, B1, B2; about 12 x 9 m by the 3 m scale bar; robot starts in E).
- **Room IDs and names:** E = entry hall, K = kitchen, LR = living room, D = dining area, B1 = bedroom 1, B2 = bedroom 2.

### D-002 Meaning of "neighbors"
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** Two rooms are neighbors if they are connected by a door. Walls shared without a door do not count.
- **Resulting adjacency (from the floorplan):** E: K, LR | K: E, LR | B1: LR | B2: LR | D: LR | LR: E, K, B1, B2, D. The entry hall E also has an exterior door.
- **Consequence:** K and D share a wall but have no door, so they are not neighbors. The grounding prompt must define "next to" as "connected by a door," and the E1 plausibility labels must follow the same definition.
- **Why:** it matches how a robot actually moves between rooms, and it is unambiguous.
- **Alternative:** shared-wall adjacency (rejected: includes pairs the robot cannot walk between directly).

### D-003 Scene graph schema
- **Date:** 2026-11-12 | **Status:** Proposed (awaiting Kristika)
- See "Interface specs" below.

### D-004 Grounding output format
- **Date:** 2026-11-12 | **Status:** Proposed (awaiting Kristika)
- See "Interface specs" below.

### D-005 Detection message
- **Date:** 2026-11-12 | **Status:** Proposed (awaiting Kristika)
- See "Interface specs" below.

---

## Grounding node design

### D-010 Library plus thin ROS wrapper
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** Grounding logic is a plain Python module with no ROS dependency. A small ROS 2 node wraps it as a service.
- **Why:** E1 needs hundreds of LLM calls without Gazebo, and unit tests are easier without ROS.

### D-011 Hosted LLM: Gemini free tier
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** Use a Gemini API model from the free tier. The model name is a config setting, not hardcoded. The API key comes from an environment variable and is never committed.
- **Notes:** The free-tier quota should be checked in the AI Studio console (Google no longer publishes per-model limits on its docs page). Free-tier requests may be used by Google to improve its products, so prompts contain only made-up commands and the floorplan. Exact model ID to be copied from AI Studio. Final E1 results report one named model.

### D-012 Local fallback: Llama via Ollama
- **Date:** 2026-11-12 | **Status:** Open (model size depends on hardware)
- **Decision:** `llama3.1:8b` if the hardware allows, otherwise `llama3.2:3b`. Use Ollama's JSON-schema `format` parameter.

### D-013 Enums in the output schema
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** The detector vocabulary and the room IDs are enums in the output JSON schema, so the model cannot name an unknown target or a nonexistent room. Validation still runs afterwards, because enums do not guarantee a sensible ranking.

### D-014 Validation, retry, fallback
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** After each LLM response, check: JSON parses and matches the schema; every target is in the vocabulary; every room ID exists; probabilities are normalized with a small floor so no room is exactly zero (search stays complete); any room constraint names real rooms. On failure, retry once with the error appended. If that fails, fall back to the keyword-to-room table (also an E1 baseline).

### D-015 Relational commands
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** The LLM resolves relational commands directly from the scene graph. The with/without scene graph ablation in E1 measures its value.

### D-016 Cache and logging
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** Cache key = command + hash of scene graph + vocabulary + model name. Every call is logged to a JSONL file (command, output, latency, model, cache hit).
- **Why:** Grounding depends only on the command and the scene graph, so E2 and E3 reuse cached answers, and the JSONL log is the E1 data.

### D-017 Prompt examples vs. test set
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** Few-shot examples in the prompt must be different from the E1 test commands.

---

## Interface specs (proposed)

All coordinates are in meters in the Nav2 `map` frame. The origin and axes must match the map file Kristika builds; this is an open point to confirm with her (see Open points).

### Scene graph (`scene_graph.json`)

Design: rooms are nodes, doors are edges. Neighbors are derived from doors, so there is one source of truth. The scene graph contains no object information, because object locations are unknown to the robot.

```json
{
  "schema_version": 1,
  "frame": "map",
  "units": "m",
  "rooms": [
    {
      "id": "K",
      "name": "kitchen",
      "polygon": [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]],
      "centroid": [2.0, 1.5],
      "area": 12.0
    }
  ],
  "doors": [
    { "id": "d_K_LR", "between": ["K", "LR"], "position": [4.0, 1.5] },
    { "id": "d_E_out", "between": ["E", "outside"], "position": [1.0, 9.0] }
  ]
}
```

Notes (the numbers above are illustrative only, not from the real layout):
- `polygon`: counter-clockwise list of [x, y] vertices.
- `centroid` and `area` are computed from the polygon by the generator; the loader checks they are consistent.
- `neighbors` is computed by the loader from `doors`, and `outside` is excluded from the neighbor lists.
- `name` is the semantic label the LLM reads. Optional field `viewpoints` can be added later by Kristika's viewpoint generator.

### Grounding output (LLM result)

```json
{
  "targets": ["banana", "apple", "sandwich"],
  "room_prior": { "K": 0.55, "D": 0.30, "LR": 0.10, "E": 0.02, "B1": 0.015, "B2": 0.015 },
  "room_constraint": null,
  "rationale": "Food is most likely in the kitchen, then the dining area."
}
```

- `targets`: non-empty, from the detector vocabulary, most likely first.
- `room_prior`: one entry for every room, sums to 1, none exactly zero.
- `room_constraint`: `null`, or a non-empty list of room IDs for explicit or relational commands (e.g., "the cup in the room next to the kitchen" gives `["E", "LR"]` under D-002).
- `rationale`: one short sentence, for logs and E1 failure analysis only. The planner ignores it.
- The planner uses `room_prior` only. `room_constraint` is for logging and scoring.

### ROS 2 interfaces (package `semantic_msgs`)

`RoomProb.msg`
```
string room_id
float32 prob
```

`GroundCommand.srv` (service `/ground_command`)
```
string command
---
bool success
string error
string[] targets
semantic_msgs/RoomProb[] room_prior
string[] room_constraint        # empty means none
string rationale
float32 latency_s
string model
bool cache_hit
```

`Detection.msg` (topic `/semantic/detections`)
```
std_msgs/Header header          # frame_id = "map"
string label                    # from the detector vocabulary
float32 confidence
geometry_msgs/Point position    # object position in the map frame
string room_id                  # room containing the point; empty if outside all rooms
string source                   # "yolo" or "oracle"
```

- Only confirmed detections (3 consecutive frames) are published.
- `source` makes it possible to report clearly when the oracle detector was used.

---

## Phase 1: Scene graph

### D-020 Placeholder scene graph
- **Date:** 2026-11-12 | **Status:** Proposed (origin convention awaiting Kristika)
- **Decision:** A placeholder `scene_graph.placeholder.json` is derived by hand from the floorplan screenshot, using the 3 m scale bar (about 62.3 px per metre). Origin is the bottom-left outer corner, x to the right, y up, coordinates rounded to 0.1 m. Door positions are estimated from the screenshot (roughly +/- 0.2 m).
- **Checks done:** total room area 108.9 m^2 matches the 12.1 x 9.0 m outline; every door lies on the boundary of the rooms it connects; neighbors derived from doors match D-002.
- **Notes:** LR is L-shaped (6 vertices, non-convex) because K cuts into its lower-left corner, so code must not assume convex rooms. The placeholder is replaced by the graph generated from Kristika's world once it exists.

### D-021 Phase 1 division of work
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** The placeholder data is produced in chat. Claude Code writes the JSON Schema file, the loader/validator, the prompt renderer, and tests. The generator from Kristika's world is deferred until her layout exists.

### D-022 Loader validation rules
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** The loader rejects a graph unless: `schema_version` is supported; room IDs are unique and `outside` is not used as a room ID; each polygon has at least 3 vertices, does not self-intersect, and is counter-clockwise; stored `area` and `centroid` match the polygon within 0.05; every door's `between` names two different known rooms (or one room plus `outside`); every door position lies on the boundary of each room it connects (tolerance 0.05 m). Neighbors are derived from doors, with `outside` excluded.

## Phase 2: Project skeleton

### D-030 Python version and packaging
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** Target Python 3.12 (`requires-python >=3.12`), setuptools backend, `src/` layout, package `lang_grounding`, dev extras `pytest` and `ruff`. No runtime dependencies yet; they are added with the features that need them.
- **Why:** ROS 2 Jazzy on Ubuntu 24.04 ships Python 3.12; the pure-Python package should run under the same interpreter as the ROS wrappers. `src/` layout prevents accidentally importing uninstalled code in tests.
- **Alternatives:** Poetry/hatch (more tooling than needed); flat layout (tests can import the source tree without installing).

### D-031 Tooling config
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** pytest (`testpaths = tests`) and ruff (line length 100, rules E, F, I, B, UP, W) configured in `pyproject.toml`. `.env` is gitignored, `.env.example` holds `GEMINI_API_KEY` and `GEMINI_MODEL` placeholders. `data/` is not ignored, so the scene graph is versioned.
- **Why:** one config file; sensible defaults without over-restricting.
- **Alternatives:** separate `pytest.ini` / `ruff.toml` (more files).

## Phase 1 (continued): scene graph implementation

### D-040 pydantic as runtime dependency
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** Add `pydantic>=2` to `dependencies` in `pyproject.toml`. Nothing else beyond the standard library. Re-run `pip install -e ".[dev]"` to get it.
- **Why:** structural parsing and typed models for the scene graph with little code; the same models are reusable for the grounding output later.
- **Alternatives:** dataclasses with hand-written parsing (more code, worse error messages); `jsonschema` package (extra dependency, see D-041).

### D-041 JSON Schema file: location and role
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** `data/scene_graph.schema.json` (draft 2020-12) is hand-written and describes structure only (fields, types, `schema_version`/`frame`/`units` constants, `minItems`). D-022 geometric rules are enforced in code, not in the schema. No `jsonschema` dependency: the pydantic models do the enforcement, and a test checks that the schema's required fields and property names match the pydantic models and the placeholder file. No fields were added or changed relative to "Interface specs".
- **Why:** gives Kristika and other tools a language-neutral definition without a new dependency; the consistency test prevents drift.
- **Alternatives:** generate the schema from pydantic (less readable, no hand-written descriptions); validate files with `jsonschema` (extra dependency, duplicate validation).

### D-042 Loaded object and error handling
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** `scene_graph.py` exposes pydantic models `Room`, `Door`, `SceneGraph`, plus `parse_scene_graph(data)` and `load_scene_graph(path)`. Neighbors are a computed property `SceneGraph.neighbors` (room ID to tuple of IDs, in file order, `outside` excluded, never stored in JSON); `exterior_rooms` lists rooms with a door to `outside`. All failures raise `SceneGraphError` (a `ValueError`). D-022 rules are checked in plain code after structural parsing, so messages name the room or door and the rule; structural errors from pydantic are reported with their JSON path (for example `rooms.0.name`). Unknown extra fields are ignored (so an optional `viewpoints` field can be added later without breaking the loader). `frame` must be `"map"` and `units` `"m"`. An empty `rooms` list is rejected; an empty `doors` list is allowed.
- **Why:** clear errors matter for debugging Kristika's generated graphs; tolerant of additive fields.
- **Alternatives:** pydantic validators for everything (messages less specific); rejecting unknown fields (would break on `viewpoints`).

### D-043 Geometry check details for D-022
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** Polygon checks run in this order: at least 3 vertices; no repeated consecutive vertices; no adjacent edges doubling back; no touching or crossing between non-adjacent edges; non-zero area; counter-clockwise (positive shoelace area); stored area within 0.05 of the shoelace area; each centroid coordinate within 0.05 of the area centroid (standard formula, valid for non-convex polygons). Doors must be within 0.05 m of the boundary of each real room they connect (distance to nearest edge segment). Orientation tests treat values below 1e-9 as zero. Duplicate door IDs are rejected (see D-046). Two doors with different IDs between the same pair of rooms are allowed; the pair appears once in the neighbor list.
- **Why:** implements D-022 as written; the order reports the most fundamental problem first (a self-intersecting polygon has no meaningful orientation or area).
- **Alternatives:** Euclidean centroid tolerance (equivalent in spirit, stricter on diagonals); requiring unique door IDs (reasonable, but beyond D-022; flagged to the user).

### D-046 Duplicate door IDs rejected (addition to D-022)
- **Date:** 2026-11-12 | **Status:** Proposed (D-022's own status is unchanged)
- **Decision:** In addition to the D-022 rules, the loader rejects a graph in which two doors share the same `id`, with the error `duplicate door ID '<id>'`. The check runs over doors in file order, before each door's other checks.
- **Why:** door IDs are references in errors and logs; duplicates make them ambiguous. Requested by the user.
- **Alternatives:** allowing duplicates (rejected by the user).

### D-044 Prompt rendering format
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** `render_for_prompt(graph)` returns plain text: a header stating that "next to", "adjacent to", "neighboring" and "beside" mean "connected by a door" and that rooms sharing only a wall are not next to each other, then one line per room: ID, name, area (1 decimal, m^2), door-connected neighbors as `ID (name)`, and a note if the room has a door to the outside. No polygons, door coordinates, or object information.
- **Why:** compact, unambiguous for the model, consistent with D-002.
- **Alternatives:** embedding the full JSON (longer, adds geometry the LLM does not need); an adjacency table only (less readable).

### D-045 CLI
- **Date:** 2026-11-12 | **Status:** Proposed
- **Decision:** `python -m lang_grounding.scene_graph validate <file>` prints `OK: <file> (N rooms, M doors)` and each room's neighbors and exits 0; on failure prints `ERROR: <message>` to stderr and exits 1.
- **Why:** quick check of generated graphs.
- **Alternatives:** none considered.

## Open points to confirm with Kristika
1. Map frame origin and axis orientation relative to the floorplan.
2. Whether the planner uses `room_prior` only (proposed) and treats `room_constraint` as informational.
3. Whether `room_id` in the detection message is computed by the detector node (proposed) or by the planner.

## Decision history
- 2026-11-12: Phase 1 scene graph implementation (D-040 to D-045) proposed.
- 2026-11-12: Phase 2 skeleton (D-030, D-031) proposed.
- 2026-11-12: Phase 1 started (D-020 to D-022); Phase 0 started; D-001, D-002 agreed; D-003 to D-005 proposed; grounding node decisions D-010 to D-017 recorded from the design discussion.
