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
- **Date:** 2026-11-12 | **Status:** Agreed
- See "Interface specs" below.

### D-004 Grounding output format
- **Date:** 2026-11-12 | **Status:** Agreed
- See "Interface specs" below.
- **Note (2026-11-15):** Kristika confirmed on Nov 15 that the planner uses `room_prior` only and that the detector computes `room_id`.

### D-005 Detection message
- **Date:** 2026-11-12 | **Status:** Agreed
- See "Interface specs" below.
- **Note (2026-11-15):** Kristika confirmed on Nov 15 that the planner uses `room_prior` only and that the detector computes `room_id`.

### D-006 Planner input from grounding
- **Date:** 2026-11-15 | **Status:** Agreed (proposed by Ansh, agreed by Kristika; answers former open point 2)
- **Decision:** The room-order planner uses `room_prior` only. `room_constraint` is informational: logged and used for E1 scoring, not for search decisions.
- **Why:** matches the proposal's planner rule, which ranks rooms by P(r | u); for relational commands the LLM already puts most of the probability on the constrained rooms, and the floor keeps every room searchable.
- **Alternatives:** restricting the search to `room_constraint` (search no longer complete if the constraint is wrong).

### D-007 Room of a detection
- **Date:** 2026-11-15 | **Status:** Agreed (proposed by Ansh, agreed by Kristika; answers former open point 3)
- **Decision:** The detector node fills `room_id` in `Detection.msg` with a point-in-polygon test of the detection's map-frame position against the scene graph rooms (empty if outside all rooms). The planner uses it as given.
- **Why:** the detector already has the map-frame position and the loaded scene graph.
- **Alternatives:** the planner computes the room (duplicate geometry code in two nodes).

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
- **Note (2026-11-15):** quota checked in AI Studio for `gemini-3.5-flash-lite` (free tier): 15 RPM, 250K TPM, 500 RPD.

### D-012 Local fallback: Llama via Ollama
- **Date:** 2026-11-12 | **Status:** Open (model size depends on hardware)
- **Decision:** `llama3.1:8b` if the hardware allows, otherwise `llama3.2:3b`. Use Ollama's JSON-schema `format` parameter.

### D-013 Enums in the output schema
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** The detector vocabulary and the room IDs are enums in the output JSON schema, so the model cannot name an unknown target or a nonexistent room. Validation still runs afterwards, because enums do not guarantee a sensible ranking.

### D-014 Validation, retry, fallback
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** After each LLM response, check: JSON parses and matches the schema; every target is in the vocabulary; every room ID exists; probabilities are normalized, then every room below a small floor (default 0.001) is held exactly at the floor and the remaining rooms are rescaled so the total is 1 (repeated if the rescaling pushes another room below the floor; details in D-103), so no room is exactly zero (search stays complete); any room constraint names real rooms. On failure, retry once with the error appended. If that fails, fall back to the keyword-to-room table (also an E1 baseline).

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

All coordinates are in meters in the Nav2 `map` frame, which equals the Gazebo world frame of `house_sim`: origin at the bottom-left outer corner of the house, x to the right, y up (D-050).

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
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** A placeholder `scene_graph.placeholder.json` is derived by hand from the floorplan screenshot, using the 3 m scale bar (about 62.3 px per metre). Origin is the bottom-left outer corner, x to the right, y up, coordinates rounded to 0.1 m. Door positions are estimated from the screenshot (roughly +/- 0.2 m).
- **Checks done:** total room area 108.9 m^2 matches the 12.1 x 9.0 m outline; every door lies on the boundary of the rooms it connects; neighbors derived from doors match D-002.
- **Notes:** LR is L-shaped (6 vertices, non-convex) because K cuts into its lower-left corner, so code must not assume convex rooms. The placeholder is replaced by the graph generated from Kristika's world once it exists.
- **Update 2026-11-14:** the placeholder is now test data only. The real scene graph is the generated `data/scene_graph.json` (D-054), and the origin convention was settled by D-050. `tests/test_scene_graph.py` and `tests/test_grounding_output.py` still read the placeholder as a stable fixture.

### D-021 Phase 1 division of work
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** The placeholder data is produced in chat. Claude Code writes the JSON Schema file, the loader/validator, the prompt renderer, and tests. The generator from Kristika's world is deferred until her layout exists.

### D-022 Loader validation rules
- **Date:** 2026-11-12 | **Status:** Agreed
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

### D-046 Duplicate door IDs rejected (addition to D-022)
- **Date:** 2026-11-12 | **Status:** Agreed
- **Decision:** In addition to the D-022 rules, the loader rejects a graph in which two doors share the same `id`, with the error `duplicate door ID '<id>'`. The check runs over doors in file order, before each door's other checks.
- **Why:** door IDs are references in errors and logs; duplicates make them ambiguous. Requested by the user.
- **Alternatives:** allowing duplicates (rejected by the user).

### D-047 Optional `viewpoints` field on rooms (addition to D-022)
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `Room` has an optional `viewpoints` field: a list of `[x, y]` map-frame points (`None` when absent; an empty list is accepted). The loader rejects a viewpoint that is not inside its room's polygon. "Inside" uses an even-odd ray-casting point-in-polygon test, so non-convex rooms (the L-shaped LR) are handled; a point within 0.05 m of the polygon boundary (`VIEWPOINT_TOL`) also counts as inside. The error names the room and the viewpoint index. `data/scene_graph.schema.json` lists `viewpoints` as an optional property of `Room` (not in `required`). `render_for_prompt` does not mention viewpoints. D-022 itself is unchanged.
- **Why:** Kristika's generator writes viewpoints into every room (D-080) and the planner may read them through this loader; a viewpoint outside its room would send the robot to the wrong place.
- **Alternatives:** keep ignoring the field (no validation of generated data); a stricter check with no boundary tolerance (rejects points exactly on a wall line due to rounding); checking viewpoint clearance from walls (that is the generator's job, D-081).

## Phase 3: Simulated house (Kristika, step 1)

### D-050 Map frame (answers former open point 1)
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** The Nav2 `map` frame equals the Gazebo world frame of `house_sim`. Origin at the bottom-left outer corner of the house, x to the right, y up, meters. The map yaml origin is `[-margin, -margin, 0]` (margin 0.5 m in the layout, so `[-0.5, -0.5, 0.0]`), i.e. the bottom-left pixel of the map image starts at (-margin, -margin).
- **Why:** set by Kristika's world; it is the same convention as the placeholder (D-020), so the scene graph, the map and Gazebo share coordinates with no extra transform.
- **Alternatives:** map origin at the image corner with a separate map-to-world transform (one more TF to keep in sync).

### D-051 Room polygons are the layout source of truth; floor rectangles are derived
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** In `layout/house_layout.yaml` each room is a counter-clockwise polygon on wall center-lines (so a door lies on the boundary of both rooms it connects), with axis-aligned edges only. LR is the 6-vertex L shape. The generator derives the Gazebo floor tiles by vertical-strip decomposition (cut at every vertex x; inside a strip, pair the crossing horizontal edges in y order). The map does not need room rectangles (the house footprint is filled free, then walls are drawn occupied). The generator rejects non-axis-aligned or clockwise polygons; a test checks that the derived rectangles cover each polygon exactly.
- **Why:** one room format, the one the scene graph needs; derived rectangles cannot drift from the polygons.
- **Alternatives:** keep rectangle lists and compute polygons from their union (harder, and the L-shape vertex order would be implicit); list polygons and rectangles separately with a coverage test (two things to edit); allow arbitrary polygons (not needed for this house, and floor tiles would need triangulation).

### D-052 Exterior door `d_E_out` is closed in the simulation
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** `d_E_out` (between E and `outside`) is at (1.8, 9.0) on E's north outer wall, 1.0 m wide; the position is taken from the placeholder (D-020). The scene graph lists it as a normal door. In Gazebo the gap is filled with a static, door-colored (brown) panel with collision, in model `house_doors`, link `door_d_E_out`: length = width - wall thickness (the clear opening between the wall ends), thickness = wall thickness, height = wall height. On the map the panel is occupied. Rule: every door to `outside` is generated closed (no per-door flag).
- **Why:** D-002 requires the exterior door in the scene graph, but the robot must not be able to leave the house or plan through it.
- **Alternatives:** leave it out of the world (world and scene graph disagree); open door (robot and Nav2 can leave the house); explicit `closed: true` flag per door (unnecessary while the only exterior door is always closed).

### D-053 Door IDs and door data
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** Door IDs are derived from the layout's `connects` pair as `d_<A>_<B>`, in the listed order, with `outside` written as `out` as in the spec example (giving d_E_LR, d_E_K, d_K_LR, d_LR_D, d_LR_B1, d_LR_B2, d_E_out, the same IDs as the placeholder). The door `center` must lie on a wall center-line, and its whole width must lie on one wall segment (the generator rejects it otherwise). Door width stays in the layout only; the scene graph keeps the spec fields `id`, `between`, `position`. Note: wall pieces are extended by half the wall thickness at both ends (unchanged existing behavior), so the clear opening is width - 0.15 m (0.85 m, or 1.25 m for d_LR_D).
- **Why:** one source for IDs; the spec format stays unchanged.
- **Alternatives:** explicit IDs in the layout (a second value that can disagree with `connects`).

### D-054 Generated scene graph file
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** The generator writes `data/scene_graph.json` at the repository root in the "Interface specs" format. Rooms appear in D-001 order (E, K, LR, D, B1, B2), doors in layout order. Polygons are copied from the layout; `area` (shoelace) and `centroid` (area centroid) are computed by the generator and rounded to 4 decimals (well inside the loader's 0.05 tolerance). Format: 2-space indented JSON with each coordinate pair and each `between` pair on one line, LF line endings, trailing newline. All generated files are written as bytes, so the output is identical on Linux and Windows. The centroid of a non-convex room is not guaranteed to lie inside it (for the current LR it does); code that uses centroids as navigation goals must check this.
- **Why:** Ansh's loader consumes it unchanged; stable formatting makes the drift test byte-exact.
- **Alternatives:** write into the ROS package and copy (two copies); full precision floats (noisy diffs such as 16.169999999999998).

### D-055 `config/rooms.yaml` removed
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** `config/rooms.yaml` is no longer generated and is deleted. Its rooms, areas, centroids, doors and door adjacency are in `data/scene_graph.json`. The launch file now reads `robot_start` from `layout/house_layout.yaml`. Dropped fields: `rects` (derivable, D-051), `shares_wall_with` (not used under D-002), door `width` (stays in the layout). `CMakeLists.txt` no longer installs `config/`. A test checks the file stays gone.
- **Why:** two room formats would drift apart.
- **Alternatives:** keep it and add a test that it agrees with the scene graph (more to maintain, no consumer needs it).

### D-056 Generator location and test import
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** The generator stays at `ros/house_sim/scripts/generate_house.py` (the package root is `ros/house_sim/`, flattened from the earlier nested `ros/house_sim/house_sim/` on 2026-11-13), next to the layout and the outputs it owns. It has no ROS imports (standard library + PyYAML; Pillow only for `--preview`). `tests/test_house_sim.py` loads it by file path with `importlib`, so plain `pytest` runs it without ROS sourced and without installing anything new. `pyyaml>=6` is added to the `dev` extras in `pyproject.toml`.
- **Why:** keeps simulation code out of `lang_grounding` and keeps the ROS package self-contained, while the tests stay ROS-free.
- **Alternatives:** move it into `src/lang_grounding` (mixes world generation into the grounding library); a second installable package under `src/` (more packaging for one script); pytest `pythonpath` setting (puts the scripts folder on the import path of every test).

### D-057 Drift test
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** A test generates into a temporary directory and compares byte-for-byte with the committed `worlds/house.sdf`, `maps/house_map.pgm`, `maps/house_map.yaml` and `data/scene_graph.json`. Text files are compared after converting CRLF to LF (so a Windows checkout with `core.autocrlf` passes); the PGM is compared exactly. `maps/house_map_preview.png` is excluded: Pillow output is not guaranteed byte-stable across versions, and the preview is a visual aid only.
- **Why:** committed outputs can never silently disagree with the layout.
- **Alternatives:** do not commit generated files (the ROS build and Ansh's tests would then depend on running the generator first).

## Phase 3 (continued): AMCL + Nav2 on the known map (Kristika, step 2)

### D-060 Navigation launch structure
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** `ros/house_sim/launch/house_nav.launch.py` includes `house_world.launch.py` (Gazebo + robot at `robot_start`), `nav2_bringup/bringup_launch.py` (map_server with `maps/house_map.yaml`, AMCL, planner, controller, behaviors, BT navigator; `use_sim_time:=true`, `autostart:=true`) and, optionally, `nav2_bringup/rviz_launch.py`. Arguments: `gui`, `rviz`. No SLAM. Nav2 is used as shipped; only its parameters are changed (D-061).
- **Why:** smallest launch that gives localization and navigation on the known map; reuses the maintained Nav2 bringup instead of re-listing its nodes.
- **Alternatives:** own launch listing every Nav2 node (more code, easy to miss a lifecycle node); `nav2_bringup/tb3_simulation_launch.py` (starts its own world and robot).

### D-061 Nav2 parameters: committed copy of the Jazzy default with marked edits
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** `ros/house_sim/config/nav2_params.yaml` is a copy of `/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml`, committed to the repo. Every change made for this house is marked with a `# house_sim:` comment, and a ROS-free test checks the edited values. The edits are made after the copy exists, so they start from the real installed default. Edits so far (base: nav2_bringup 1.3.13): AMCL `set_initial_pose`/`initial_pose` (D-062) and `laser_max_range` 3.5 (TurtleBot3 LDS); MPPI `vx_max`/`vx_min` ±0.26 and `wz_max` 1.82, and velocity smoother limits [±0.26, 0, ±1.82] (Waffle limits; the default 0.5 m/s makes MPPI plan for speeds the robot cannot reach); `enable_stamped_cmd_vel: true` on every node that publishes velocity (the TurtleBot3 Jazzy bridge takes TwistStamped on `/cmd_vel`). Unchanged on purpose: `robot_radius` 0.22, inflation radius 0.7 and cost scaling 3.0 (the narrowest clear opening, 0.85 m, still leaves a 0.35 m corridor for the robot center); tuning comes with the clutter step.
- **Why:** reproducible (the file used in experiments is versioned); later tuning (inflation, MPPI or DWB, recoveries; proposal Nov 20–25) edits the same file.
- **Alternatives:** writing the file from scratch (easy to miss a required key, e.g. the Jazzy docking server); rewriting the installed default at launch time with `RewrittenYaml` (small, but the base file can change with a package update, unnoticed).

### D-062 Initial pose comes from the layout
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** AMCL starts at the layout's `robot_start` through `set_initial_pose`/`initial_pose` in `nav2_params.yaml`; a test checks that the two agree. The room tour script also sets the same pose through `BasicNavigator.setInitialPose`, because `waitUntilNav2Active` otherwise republishes a zero initial pose.
- **Why:** the robot is localized at launch without clicking "2D Pose Estimate", and the spawn pose, AMCL and the tour can not disagree.
- **Alternatives:** manual pose estimate in RViz (not repeatable for headless trials).

### D-063 One goal per room for navigation checks
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** `ros/house_sim/scripts/room_goals.py` (ROS-free) picks, for each room polygon, the 0.05 m grid point that is farthest from the polygon boundary (wall center-lines), ties broken by distance to the area centroid. Goals are computed at run time from the layout polygons, not stored. Tests check that every goal is inside its own room only and at least 0.5 m from every wall surface and the closed exterior door.
- **Why:** the centroid of the L-shaped LR is not guaranteed to be inside it (D-054); this point always is, with maximum clearance.
- **Alternatives:** centroids (can fall outside non-convex rooms); hand-picked goals (another list to keep in sync). Viewpoints for the search (proposal Step 2) are a separate later step and may replace these goals.

### D-064 Room tour as the Nav2 acceptance check
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** `ros2 run house_sim room_tour.py` (needs `house_nav.launch.py` running, robot at the start) sends goals to K, LR, D, B2, B1, E in that order with `nav2_simple_commander`, prints the result and time for each room, and exits 1 if any goal fails or times out (default 180 s per goal). This passes through every interior door at least once. It is a manual ROS check, not part of `pytest`.
- **Why:** the proposal's milestone for this step is reliable navigation into every room on the known map.
- **Alternatives:** clicking goals in RViz (not repeatable); a launch_testing test (needs Gazebo in CI, too heavy for now).

## Phase 3 (continued): target objects (Kristika, step 3)

### D-070 Placeholder target objects per COCO class
- **Date:** 2026-11-14 | **Status:** Agreed (class list updated 2026-11-15)
- **Decision:** `ros/house_sim/objects/catalog.yaml` has one entry for every class of the detector vocabulary (`configs/vocabulary.json`, D-100), keyed by exact COCO name: banana, apple, orange, sandwich, bottle, cup, bowl, book, laptop, remote, cell phone, teddy bear. A test checks that the catalog and the vocabulary have the same classes. Each is a simple shape (box, cylinder or sphere) at about real size with a distinct color. Objects are static models with one collision and one visual, so the robot cannot push them away and the touch step can register contact. Realistic models (Gazebo Fuel where available) replace the shapes with the YOLO switch (proposal Nov 20–25).
- **Why:** the oracle detector (used first) does not need realistic appearance; no dependency on downloading models now.
- **Alternatives:** Fuel models now (network at run time, availability per class not checked yet); dynamic objects (can be pushed or knocked over by the robot, which moves the ground truth).

### D-071 Scenario files
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** A scenario is `ros/house_sim/objects/scenarios/<name>.yaml` with a list of objects: `label` (catalog class), `room`, `xy` (map frame) and `yaw`. The room is stored for readability and for later plausible/implausible bookkeeping, and is checked against the polygons. `demo.yaml` places one object of every class in a plausible room. Per-trial random placement (80% plausible, 20% implausible, fixed seeds) belongs to the evaluation harness and is not part of this step.
- **Why:** a fixed, readable placement for the first end-to-end runs and for Ansh's oracle detector; the harness can later write files in the same format.
- **Alternatives:** objects baked into `house.sdf` (every placement change needs a regenerated world); random placement now (harness work, out of scope).

### D-072 Object placement rules
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** Each object (its footprint circle) must be inside its declared room and at least 0.3 m from wall surfaces and the closed exterior door, 0.5 m from every door gap, 0.6 m from every room tour goal (D-063), 0.8 m from the robot start, and 0.3 m from every other object. `scripts/house_objects.py` checks this before spawning; tests cover each rule.
- **Why:** most objects are lower than the Waffle's lidar plane, so Nav2's costmaps cannot see them; keeping them off doorways, tour goals and the start keeps navigation from driving into them. 0.5 m from doorways is the proposal's clutter rule.
- **Alternatives:** no rules (a placement can block a doorway or sit on a goal); adding the depth camera to the costmap (a Nav2 tuning change for the clutter step).

### D-073 Spawning objects and model names
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** `ros2 launch house_sim spawn_objects.launch.py scenario:=demo` spawns a scenario into the running world (`house`) with `ros_gz_sim create`, one call per object, after the placement check. Gazebo model names are `obj_<label>_<k>`, with spaces in the label replaced by underscores and `k` counting objects of the same class from 0 (e.g. `obj_teddy_bear_0`); `house_objects.label_from_model_name` maps a name back to the COCO label.
- **Why:** objects change per trial without regenerating the world; the name alone tells the oracle detector the class.
- **Alternatives:** spawning from a Python node through the Gazebo service (more code than the existing `create` tool); names without the class (the oracle would need the scenario file to know the label).

### D-074 Truth files for the oracle detector
- **Date:** 2026-11-15 | **Status:** Agreed (proposed by Ansh, agreed by Kristika; answers former open point 4)
- **Decision:** `python ros/house_sim/scripts/house_objects.py [scenario ...]` writes `data/objects_<scenario>.json` (default: every scenario in `objects/scenarios/`) from the same scenario file and placement code the spawner uses. Format: `scenario`, `frame` (`"map"`), `units` (`"m"`) and `objects`, in spawn order, each with `name` (Gazebo model name, D-073), `label` (COCO class), `room`, `position` [x, y, z] (center of the object; z is half its height), `yaw`, `height` and `radius` (footprint circle). Ansh's oracle detector reads this file and filters by the camera's field of view. A test checks that the committed `data/objects_demo.json` matches the generator.
- **Why:** target objects are static (D-070), so the file stays true for the whole trial; no Gazebo pose bridge needed.
- **Seeding:** target placements are fixed scenario files, so every method sees the same targets; clutter is seeded (D-092). Random 80/20 target placement (evaluation harness) must also be seeded and write a scenario file, so this truth file covers it.
- **Alternatives:** object poses from Gazebo through a pose bridge (more moving parts; only needed if objects could move).

## Phase 3 (continued): search viewpoints (Kristika, step 4)

### D-080 Viewpoints in the scene graph
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** The generator adds `"viewpoints": [[x, y], ...]` to every room in `data/scene_graph.json`: 1–3 map-frame positions, sorted by x then y, rounded to 1 mm. At each viewpoint the robot turns 360°; viewpoints have no heading. The loader already ignores unknown fields (D-042), and the JSON Schema does not forbid extra properties, so the graph still validates. Settings live in a `viewpoints` section of `house_layout.yaml` (camera range, wall clearance, maximum per room, grid sizes). `maps/house_map_preview.png` marks viewpoints as green squares.
- **Why:** the "Interface specs" note reserves this optional field for Kristika's viewpoint generator; one file holds everything the planner needs about rooms.
- **Alternatives:** a separate viewpoints file (another file to keep in sync with the graph); storing the robot heading too (not needed for a 360° turn).
- **Loader side:** D-047 (Ansh) reads the field and checks each viewpoint is inside its room. Order has no meaning (the planner chooses the visiting order); no heading.

### D-081 Viewpoint coverage model and selection
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** A floor point counts as seen from a viewpoint if it is within `camera_range` (3.0 m) and the straight line to it stays inside the room polygon (matters for the L-shaped LR). Floor points are sampled every 0.2 m, at least 0.05 m beyond the wall surfaces; candidate viewpoints every 0.25 m, at least 0.5 m from wall surfaces so the robot can turn in place. Selection: the fewest viewpoints (up to 3) that see every floor sample; among those, the set that does so with the smallest range (tried in 0.25 m steps up to 3.0 m), so each viewpoint sits near the middle of what it covers; ties go to the set whose viewpoint closest to a wall is farthest from it, then to grid order. Search is exhaustive over candidate sets, so the result is deterministic and the count is minimal on the grid. Result for this house: E 1, K 2, LR 2, D 1, B1 2, B2 2 (10 in total). The generator stops with an error if a room needs more than 3.
- **Why:** follows the proposal ("1–3 viewpoints per room, chosen from its polygon so the camera covers the room during a 360° rotation"); the count feeds the planner's search cost.
- **Assumptions to revisit:** 3.0 m is an assumed detection range for small COCO objects, not measured; occlusion by furniture and clutter is ignored; the camera's minimum range and floor visibility close to the robot are ignored. Tune `camera_range` once the detector is tested.
- **Alternatives:** greedy set cover (fewer computations, but in K it picks the center first and then needs two more viewpoints for the corners: 3 where 2 suffice); fixed viewpoints by hand (another list to keep in sync).

## Phase 3 (continued): clutter (Kristika, step 5)

### D-090 Clutter types
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** `ros/house_sim/objects/clutter.yaml` defines three clutter types as static placeholder shapes: box (0.4 m cube), bin (cylinder, 0.15 m radius, 0.5 m tall) and chair (0.45 × 0.45 × 0.85 m box). All are at least 0.3 m tall, above the Waffle's lidar plane, so Nav2's obstacle layers see them. Clutter is never written to the static map. Gazebo model names are `clutter_<type>_<k>`.
- **Why:** proposal Step 3 ("boxes, chairs, bins", only in the costmaps through the lidar); static so a collision cannot push clutter out of the way unnoticed.
- **Alternatives:** Fuel furniture models (later, with the realistic target models); dynamic clutter (pushable, changes the trial).

### D-091 Clutter placement rules and reachability check
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** Each clutter object (footprint circle) must be inside a room and at least 0.15 m from walls, 0.5 m from every door gap (proposal), 0.5 m from every viewpoint and room tour goal (the robot stops and turns there), 0.8 m from the start, 0.6 m from target objects, and 0.3 m from other clutter. In addition, after each object is placed, a flood fill on a 0.1 m grid (robot radius 0.22 m, the Nav2 value, plus 0.03 m margin) checks that every viewpoint and room tour goal is still reachable from the start, and that every target still has a reachable cell within 0.7 m; a candidate that breaks this is rejected.
- **Why:** proposal: "kept at least 0.5 m from doorways, so no room becomes unreachable"; the door rule alone does not guarantee this (clutter could close off part of a room or a viewpoint), the flood fill does.
- **Consequence:** viewpoints are never blocked, so the proposal's recovery case "viewpoint blocked: try the next viewpoint, then skip the room" is not exercised by placed clutter. Narrow passages between clutter can still be costly for Nav2.
- **Alternatives:** only the doorway rule (rooms can be cut off); allowing clutter on viewpoints (exercises recovery, but makes success rates depend on placement luck).

### D-092 Random, seeded clutter spawning
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** `scripts/clutter.py` (ROS-free) draws positions uniformly over the house footprint, a type uniformly from the catalog and a uniform yaw from `random.Random(seed)`, and rejects candidates that break D-091 (up to 1000 tries per object, then an error). The same count and seed give the same placement. `ros2 launch house_sim spawn_clutter.launch.py count:=N seed:=S scenario:=demo` spawns 0–10 objects into the running world and logs where they went; `scenario` names the target objects to keep clear of (`none` for no targets). Collision counting from Gazebo contact events and the per-trial seed list belong to the evaluation harness.
- **Why:** proposal: "0–10 clutter objects spawned at random free locations", "fixed seed list, so every method sees identical conditions".
- **Alternatives:** hand-made clutter scenarios (not random); sampling per room (uneven density in small rooms).

## Phase 3 (continued): trial launch and touch acceptance (Kristika, step 8)

### D-093 One-command trial setup
- **Date:** 2026-11-16 | **Status:** Proposed
- **Decision:** `ros2 launch house_sim trial.launch.py scenario:=<name|none> clutter_count:=<0-10> clutter_seed:=<n> [spawn_delay:=20.0] [gui:=…] [rviz:=…]` includes `house_nav.launch.py` and, after `spawn_delay` seconds (wall clock, so Gazebo is up), `spawn_objects.launch.py` (unless `scenario:=none`) and `spawn_clutter.launch.py` (only if `clutter_count` > 0, keeping clear of the same scenario's targets). Defaults: demo targets, no clutter.
- **Why:** every trial of E2–E4 must start from the same world for a given scenario and seed (proposal: fixed seed list); one command removes the forgotten-respawn mistake seen after restarts.
- **Alternatives:** separate commands per trial (easy to forget a step); spawning inside the evaluation harness (not built yet; it can call this launch).

### D-094 Touch acceptance against Gazebo ground truth
- **Date:** 2026-11-16 | **Status:** Proposed
- **Decision:** `touch_target.py --truth` reads the robot's true pose with `gz model -m waffle -p` right after the touch (before the back-off) and prints `TRUTH <name>: gap … m, bearing … deg, PASS|FAIL`. The true gap is the distance from the robot's front-face center (0.0685 m ahead of `base_link`) to the nearest point of the object's real footprint (`scripts/touch_check.py`, ROS-free: a rotated rectangle for boxes, a circle for cylinders and spheres); PASS means gap ≤ 0.15 m and that point within 15° of the robot's heading (proposal: within 0.15 m while facing the target). `ros2 run house_sim touch_all.py [--scenario demo] [--names …]` runs `touch_target.py --truth` for every object in turn (with back-off between them) and prints a summary; exit 0 if all pass. Tests reproduce the two verified runs from their Gazebo poses (bottle 0.136 m, banana 0.047 m).
- **Why:** the controller's own gap comes from its estimate; acceptance must not rely on the thing it checks. Gazebo's pose is the simulator's ground truth.
- **Note:** this checks touches in the simulator only; in E2–E4 the harness should use the same check for the touch-success metric.
- **Alternatives:** comparing with the AMCL pose (4–15 cm off near targets); the circle footprint for boxes (wrong by up to 7 cm for the banana).

## Phase 3 (continued): contact sensor (Kristika, step 6)

### D-095 Robot model copy with a contact sensor
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `ros/house_sim/models/turtlebot3_waffle_bumper/model.sdf` is a copy of `turtlebot3_gazebo` 2.3.7 `models/turtlebot3_waffle/model.sdf` (Apache-2.0, attribution kept), with one marked change: a contact sensor `bumper` on `base_link`, watching the body box `base_collision` (0.265 × 0.265 × 0.089 m), publishing `gz.msgs.Contacts` on gz topic `bumper` at 50 Hz. It reports every contact of the body: targets (touch step), clutter and walls (collision counting in E3). Meshes still come from `model://turtlebot3_common`. The world already loads `gz-sim-contact-system`.
- **Limit:** the body box starts 0.0135 m above the floor, so the 0.01 m cell phone cannot touch it (the wheels hit it instead); a test lists such classes. For those, the touch step must use the proposal's other criterion (stop within 0.15 m while facing the target).
- **Why:** proposal Step 4 ("until the bumper reports contact"); the stock simulated Waffle has no contact sensor. Same pattern as D-061: a committed copy with marked edits.
- **Alternatives:** patching the installed model at launch (depends on the installed file silently); contact sensors on the wheels too (wheel contacts with the floor are constant noise).

### D-096 Own spawn and bridge for the robot
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `house_world.launch.py` no longer includes `turtlebot3_gazebo/spawn_turtlebot3.launch.py`. It runs the same three nodes itself: `ros_gz_sim create` with the model copy (name `waffle`, z 0.01, and now also the layout's start `yaw`), `ros_gz_bridge parameter_bridge` with `config/robot_bridge.yaml`, and `ros_gz_image image_bridge` for `/camera/image_raw`. `robot_bridge.yaml` is a copy of the upstream `turtlebot3_waffle_bridge.yaml` (marked as such) plus `/bumper` (`ros_gz_interfaces/msg/Contacts`). `robot_state_publisher` still comes from `turtlebot3_gazebo`.
- **Why:** the upstream spawn launch hard-codes the stock model and its bridge file.
- **Alternatives:** a second bridge node only for `/bumper` next to the upstream spawn (the upstream spawn would still spawn the stock model without the sensor).

### D-097 Depth camera on the robot
- **Date:** 2026-11-15 | **Status:** Proposed (new topics for Ansh's detector)
- **Decision:** The model copy (D-095) gets a second camera sensor, `depth_camera` (type `depth_camera`), in the same link as the RGB camera (`camera_rgb_frame`), at the link origin like the RGB sensor, with the same horizontal FOV (1.02974 rad) and the same 16:9 aspect, at 640 × 360 and 15 Hz, clip 0.05–10 m. Depth is in meters (32-bit float). ROS topics: `/camera/depth/image_raw` (`sensor_msgs/Image`, through `ros_gz_image image_bridge`) and `/camera/depth/camera_info`. RGB pixel (u, v) corresponds to depth pixel (u/3, v/3). The RGB camera and its topics are unchanged.
- **Frame convention (for Ansh):** both images carry `frame_id` `camera_rgb_frame`, the TurtleBot3 body-style frame (x forward, y left, z up), not an optical frame (z forward). Projecting a pixel with depth into the map needs that rotation applied.
- **Why:** proposal: the detector projects detections "to the map frame using depth and TF", and the touch step stops when "the depth reading is below 0.15 m"; the stock simulated Waffle camera is RGB only.
- **Alternatives:** replacing the RGB camera with an `rgbd_camera` sensor (one sensor, but it renames the existing RGB topic); depth at the full 1920 × 1080 (exact pixel match, but much heavier to render under WSL).

## Phase 3 (continued): approach and touch (Kristika, step 7)

### D-098 Approach-and-touch logic
- **Date:** 2026-11-15, revised 2026-11-16 | **Status:** Proposed
- **Decision:** `ros/house_sim/scripts/touch_logic.py` (ROS-free).
  - *Standoff* (map frame, Nav2): 16 poses on a circle of radius (target footprint radius + 0.5 m) around the target, facing it, kept only if inside a room and at least 0.32 m from known walls (robot radius 0.22 + 0.1), closest to the robot first.
  - *Final approach in the odom frame:* the target's known map position is moved into the odom frame once (through the robot's AMCL and odometry poses at that instant) and then tracked. Each new depth image is searched in a ±60 px column band around the estimate's expected column (bearing seen from the camera, which sits 0.069 m ahead of and 0.047 m right of `base_link`), every 4th pixel. Floor pixels are ignored: a pixel counts as an object only if it is at least 0.03 m closer than the floor would be in its row (camera 0.117 m above the floor, square pixels). A sighting closer than 0.02 m beyond the depth at which the target's near side leaves the bottom of the image ((0.117 m − near-side height) × focal length / half image height; near-side height = height of a box or cylinder, radius of a sphere, from the catalog; e.g. 0.24 m for the banana, never for objects taller than the camera) is ignored: it can only be the far part of a low object, and using it pushed the simulated banana's estimate about 6 cm too far. The nearest object pixel gives the target center (one radius beyond it along the camera axis); a sighting within 0.25 m of the estimate is blended in with weight 0.5, others (walls, clutter) are ignored. Between sightings, and after a small object drops below the image at close range, wheel odometry carries the estimate. Until the first sighting, the whole image width is searched, a sighting up to 0.40 m from the estimate is accepted, and it replaces the estimate outright instead of being blended (half-blending left the estimate 0.1 m off, outside the narrow band, and the target was lost again) (the starting estimate carries the full AMCL error; in the acceptance run the cup was ~0.25 m to the side, outside the ±60 px band, and was never seen).
  - *Servo* (about 20 Hz, on the tracked estimate): turn in place while the bearing error is above 0.1 rad (turn rate 1.5 × error, at most 0.5 rad/s); otherwise drive at 0.4 × remaining gap, clamped to 0.03–0.08 m/s, with the same heading correction.
  - *Stop rules,* in order: bumper contact with the target (success, `contact`); bumper contact with anything else (failure, `blocked:<model>`); facing the target (bearing error ≤ 15°) and this cycle's accepted target depth ≤ 0.14 m (success, `depth`; 1 cm under the proposal's 0.15 m because the true gap is slightly larger than the depth when not square-on); facing and the estimated gap from the body's front face (0.0685 m ahead of `base_link`) to the target footprint ≤ 0.05 m (success, `gap`). Before those: if the camera has never confirmed the target by the time the estimated gap is 0.30 m, stop with `unseen` (failure): the estimate is then only AMCL's guess, and in the acceptance run that reported a false success 0.19 m from the cup, beside it.
- **Why:** proposal Step 4 ("standoff pose 0.5 m from it", "drives forward slowly until the bumper reports contact or the depth reading is below 0.15 m"; touch success is contact or ≤ 0.15 m while facing). The camera is 0.117 m above the floor with a 17.7° half vertical field of view, so near the end small objects (banana, book, remote, laptop, sandwich, cell phone) drop below the image; the 0.01 m cell phone is also below the bumper (D-095); the gap stop covers those cases.
- **Revision (2026-11-16):** the first version took the minimum depth over a narrow column band and the gap from AMCL. In the Gazebo runs the band minimum was the floor (0.37 m at the bottom rows) until the target was closer than that, and AMCL was 4–11 cm off near the targets, so the depth stop never fired and the gap stop ended up to ~16 cm short. Hence the floor filter, the odom frame and the depth-corrected estimate. A test renders the depth image of a cylinder and starts the estimate 0.11 m off: a tall bottle stops on depth within 0.15 m, a low banana on the gap stop within 0.07 m.
- **Simplification:** the target is found by its expected position and the nearest object pixel, not by centering a bounding box as the proposal describes; the oracle detector gives positions, not boxes. With YOLO, the box can choose the column band instead.
- **Alternatives:** AMCL-only gap (5–10 cm error, too coarse for a 0.15 m tolerance); bumper only (misses the cell phone, and contact with a static object can push the robot sideways); centering on the nearest pixel without a position prior (can lock onto walls or clutter).

### D-099 Touch command for one target
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `ros2 run house_sim touch_target.py --name <model name> [--scenario demo]` takes the target from the scenario (the same `place_objects` data as `data/objects_<scenario>.json`, D-074), drives to the standoff with Nav2 (up to 4 candidates, 300 s simulated time each), then runs the servo of D-098 for at most 60 s simulated time, publishing `TwistStamped` on `/cmd_vel` directly, reading `/bumper` and `/camera/depth/image_raw`, and the robot pose from TF (`map` → `base_link` for the standoff, `odom` → `base_link` for the final approach and back-off, D-098). It prints `RESULT <name>: SUCCEEDED|FAILED (<outcome>)` with the final gap and bearing error (both from the tracked estimate), the number of accepted depth sightings and how far the estimate moved from its AMCL-based start, and exits 0 on success. It assumes AMCL is already localized and does not reset the initial pose. It does not call `BasicNavigator.waitUntilNav2Active()` (a lost lifecycle `get_state` reply under WSL hung a run forever); `goToPose()` waits for the `NavigateToPose` action server instead. TF is received on a separate node with its own spin thread, and the servo loop handles all waiting messages each cycle; with TF on the navigator node the pose went stale behind the depth images and the first bottle run oscillated and timed out (2026-11-15). The servo prints its state once per simulated second. After the result, the robot backs off straight at 0.05 m/s until the gap is 0.30 m (at most 20 s simulated time; stops if the bumper touches anything else; `--no-back-off` skips it): next to a tall target the robot is inside the target's lethal costmap zone, and Nav2 could not plan the next goal from there (seen 2026-11-15: the bowl run after the bottle hung in recoveries). Later the planner calls the same logic with the target from a `Detection` message (D-005) instead of a name.
- **Why:** user choice (2026-11-15): start with the truth data now rather than wait for Ansh's `semantic_msgs`.
- **Alternatives:** waiting for `Detection.msg`; a plain x y argument (no link to object names).

## Phase 4: Grounding output schema and validator

### D-100 Vocabulary config and loader
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** The detector vocabulary lives in `configs/vocabulary.json` as an object with a `"vocabulary"` list of COCO class names: banana, apple, orange, sandwich, bottle, cup, bowl, book, laptop, remote, cell phone, teddy bear (12 classes, as specified by the user). `load_vocabulary(path=None)` reads it (default: the repo's `configs/vocabulary.json`, found relative to the source tree, so it assumes an editable install or a source checkout). The override is a `path` argument; `build_output_schema` and `validate_grounding` also accept any list of names directly. A vocabulary that is empty, has duplicates, or has non-string entries raises `VocabularyError`.
- **Why:** D-011/D-013 say the vocabulary is configuration; accepting a list lets tests and experiments swap it without files.
- **Note:** Kristika's `objects/catalog.yaml` (D-070) now contains all 12 vocabulary classes: orange, bowl and cell phone were added on 2026-11-15, and a test checks that the catalog and the vocabulary have the same classes.
- **Alternatives:** hardcoded constant (violates D-013's config intent); a bare JSON list (no room for a description); environment variable for the path (not needed yet).

### D-101 Output JSON Schema form
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `build_output_schema(graph, vocabulary)` returns a plain JSON Schema dict. `targets`: array of strings with the vocabulary as `enum`, `minItems` 1, `uniqueItems`. `room_prior`: object whose property names are the room IDs (all required, `additionalProperties: false`), values numbers in [0, 1]; JSON Schema cannot put enums on object keys, so the IDs are fixed property names. `room_constraint`: `anyOf` null or a non-empty unique array of room-ID enum values. `rationale`: string, `maxLength` 300. Required: `targets`, `room_prior`, `room_constraint`; `rationale` is optional. Top level has `additionalProperties: false`. No `$schema` key.
- **Why:** D-013 (enums so the model cannot name unknown targets or rooms); matches "Interface specs".
- **Open for the backend step:** Gemini's structured-output mode accepts only a subset of JSON Schema (for example, it may not accept `anyOf` with null or `additionalProperties`), and Ollama's `format` takes standard JSON Schema. The Gemini adapter will convert this schema if needed; the validator below is the real gate (D-013).
- **Alternatives:** `room_prior` as a list of `{room, prob}` objects with a room enum (an enum on the room is possible, but it allows duplicates and omissions, which the schema cannot forbid); pydantic-generated schema (less control over the wording).

### D-102 Validator interface
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `validate_grounding(data, graph, vocabulary, *, floor=0.001)` returns a `GroundingResult` (frozen pydantic model: `targets`, `room_prior`, `room_constraint`, `rationale`) or a non-empty `list[str]` of errors. Callers check with `isinstance`. All problems found are reported together, each prefixed with the field (for example `room_prior[D]: must be between 0 and 1, got 1.5`) and, where useful, naming the valid choices, so the list can be appended to a retry prompt (D-014). The response must be a JSON object; unexpected top-level keys are errors; `targets`, `room_prior` and `room_constraint` must be present (`room_constraint` may be `null`); `rationale` may be absent or `null` (stored as an empty string). Bad `vocabulary` or `floor` arguments are programming errors and raise instead of returning errors. Duplicate keys inside `room_prior` cannot be detected after JSON parsing (the parser keeps the last value); only the schema and the backend's parser can prevent them.
- **Why:** one retry prompt can fix everything at once; strict presence of `room_constraint` matches the schema.
- **Alternatives:** stop at the first error (more retries); raise an exception carrying the error list (callers must catch); lenient defaults for missing fields (hides model mistakes in E1 failure analysis).

### D-103 Probability handling
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** Each probability must be a finite number (not a boolean) in [0, 1]. If the sum is within 0.05 of 1 (inclusive), the values are divided by the sum; otherwise the response is rejected. The floor (default 0.001, configurable, must satisfy floor times the number of rooms < 1) is then applied: every room below the floor is set to exactly the floor and the remaining rooms are rescaled so the total is 1; if the rescaling pushes another room below the floor, that room is lifted too, repeating until none is (at most one pass per room). The result sums to 1 and no room is below the floor. A floor of 0 disables flooring.
- **Why:** D-014 ("normalized with a small floor so no room is exactly zero"). A single clamp-then-renormalize step would leave floored rooms slightly under the floor (for example 0.00099); holding them at the floor avoids that and keeps the ranking order.
- **Alternatives:** clamp then renormalize once (as literally worded; floored rooms end marginally below the floor); mixing with a uniform distribution (changes every probability, even when no room is near zero).

## Phase 4 (continued): grounding loop, backends, cache, logging

### D-104 HTTP with the standard library; no new dependencies
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** Both LLM backends talk to their servers with `urllib.request` through one injectable function (`HttpPost`), so no client library is added. `pyproject.toml` is unchanged (pydantic remains the only runtime dependency).
- **Why:** the two APIs need one JSON POST each; the injectable function makes every test network-free; fewer packages to install on the Ubuntu/ROS machine.
- **Alternatives:** the `google-genai` SDK and the `ollama` Python package (convenient, but extra dependencies with their own version churn, and harder to mock precisely); `requests` (extra dependency for one POST).

### D-105 Settings in `configs/grounding.json`
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `configs/grounding.json` holds the settings (loaded and validated by `config.py`, unknown keys rejected): Gemini (`model`, `timeout_s`, `temperature`), Ollama (`model` = `llama3.1:8b`, `host`, `timeout_s`, `temperature`), `floor`, and the paths of the scene graph, vocabulary, keyword table, prompt files, cache directory (`.cache/grounding`) and log file (`logs/grounding.jsonl`; both directories are gitignored). Relative paths resolve against the repository root. The Gemini model is `null` in the file and comes from the `GEMINI_MODEL` environment variable (as in `.env.example`) or from that setting; no Gemini model ID is written in code. The key comes only from `GEMINI_API_KEY`. A missing key or model raises `ConfigError` at start-up; it does not fall back silently. `.env` is not read automatically (it would need another dependency); export the variables (see the README commands in the hand-off).
- **Why:** D-011 (model name is a config setting; key from the environment) and D-012 (Ollama default is a setting, still Open).
- **Alternatives:** a `.env` loader such as python-dotenv (extra dependency); defaults inside the code (hardcoded model names).
- **Note (2026-11-15):** the sentence ".env is not read automatically" is amended by D-120: `.env` is now read automatically by a small standard-library loader, so the export step is no longer needed.

### D-106 Backend interface and typed errors
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** A backend has a `model` attribute and `generate(system_prompt, user_prompt, json_schema) -> BackendResponse(text, latency_s, model)`. Errors: `BackendError` (base: network failure, other HTTP errors), `BackendTimeoutError` (socket timeout, HTTP 408 or 504), `BackendRateLimitError` (HTTP 429, quota exhausted), `BackendResponseError` (answer arrived but is not in the expected format: not JSON, no candidates, no text, no `message.content`). Missing configuration is a separate `ConfigError`, not a `BackendError`.
- **Why:** the grounding loop treats every `BackendError` the same (fallback), but logs the type; setup mistakes must not hide behind the fallback.
- **Alternatives:** one generic error (loses the reason in E1 logs); retrying on timeouts or rate limits (not asked; a rate-limited retry rarely helps).

### D-107 Gemini backend and schema conversion
- **Date:** 2026-11-14 | **Status:** Agreed
- **Decision:** REST call `POST {base}/v1beta/models/{model}:generateContent` with the key in the `x-goog-api-key` header (never in the URL, body, repr, errors or logs), `systemInstruction`, one user `contents` entry, and `generationConfig` with `temperature` 0, `responseMimeType: application/json` and `responseSchema`. Thought parts in the answer are ignored. `to_gemini_schema()` (pure function, `backends.py`) converts our JSON Schema to the `responseSchema` subset: **kept** `type`, `enum`, `properties`, `required`, `items`, `description`, `minItems`, `maxItems`, `minimum`, `maximum`, `minLength`, `maxLength`; **dropped silently** `$schema`, `$id`, `title`, `additionalProperties`, `uniqueItems`; **rewritten** type names to upper case (`string` to `STRING`) and `anyOf: [{type: null}, X]` to X with `nullable: true`; **rejected with an error** anything else (other `anyOf` shapes, `const`, `$ref`, `oneOf`, `not`, unknown keywords). Enums are kept everywhere. The validator still enforces what the dropped keywords expressed (no extra properties, unique entries).
- **Verified live on 2026-11-15** with one easy command ("find the banana") against `gemini-3.5-flash-lite`: `responseSchema` was accepted, upper-case type names were accepted, `nullable` was accepted, the dropped keywords were harmless, and the answer was valid on the first try. Still untested: relational commands, the retry path against the real API, and free-tier rate limits.
- **Why:** D-013 (enums in the schema) and the open point in D-101 about Gemini's subset.
- **Alternatives:** `responseJsonSchema` (accepts more of JSON Schema, but its support depends on model and API version); keeping `anyOf` (not reliably supported); dropping unknown keywords silently (hides schema changes).

### D-108 Ollama backend
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `POST {host}/api/chat` with `model`, a system and a user message, `format` set to the full unconverted JSON Schema, `stream: false` and `options.temperature` 0; the answer is `message.content`. Default model `llama3.1:8b` from the config (D-012 stays Open). Connection refused is a `BackendError`; the timeout is `ollama.timeout_s`.
- **Why:** D-012; Ollama's structured outputs take standard JSON Schema.
- **Alternatives:** `/api/generate` (no separate system message in the same shape).

### D-109 Fake backend
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `FakeBackend(script=None, model="fake-model", latency_s=0)` consumes one scripted item per call (text, dict or list as JSON, or an exception instance that is raised) and records every call. An exhausted script raises `BackendError`. Without a script it returns a valid uniform response built from the schema (first vocabulary class, equal probability per room), so the CLI works offline.
- **Why:** tests of the loop need exact control over answers and errors.
- **Alternatives:** unittest.mock objects (more verbose, no offline CLI use).

### D-110 Prompt builder and prompt files
- **Date:** 2026-11-14 | **Status:** Proposed (amended by D-116: the real prompt files replaced the placeholders and use a different format)
- **Decision:** `configs/prompts/system.md` is the system template and must contain `{scene_graph}`, `{vocabulary}` and `{examples}` (a template missing one is a `ConfigError`); filling is single-pass, so inserted text is never substituted again. `configs/prompts/fewshot.json` is `{"examples": [{"command", "response"}]}`; examples are rendered into the system prompt as `Example N / Command / Response (JSON)`. The user prompt is `Command: <command>`. The scene graph text is `render_for_prompt` (D-044) and the vocabulary a comma-separated list from the config. The retry prompt is the original user prompt plus the validator's errors as a bullet list and a request for a corrected JSON object. The placeholder example is "search the dining area for a bowl" (not an E1 command). Checking the real examples against the E1 commands (D-017) is not automated yet.
- **Why:** D-017; the backend interface carries only a system and a user prompt, so examples go in the system prompt.
- **Alternatives:** examples as chat turns (needs a message list in the backend interface); Python `str.format` (clashes with JSON braces).

### D-111 The grounding loop
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `ground(command, graph, vocabulary, backend, cache, logger, *, prompts, keyword_table, floor)` (the last three default to the config files): reject an empty command; render the prompts; look up the cache; otherwise call the backend with the response schema, parse the text as JSON (a Markdown code fence around it is tolerated), validate with `validate_grounding` (unchanged); on invalid output, one retry whose user prompt has the errors appended (D-014); if the second answer is also invalid, or any `BackendError` occurs (no retry for those), use the keyword fallback (D-112). The result, `GroundOutcome`, carries `source` (`llm`, `cache` or `fallback`), `attempts` (backend calls, 0 for a cache hit, at most 2), `latency_s` (wall-clock time of the whole call, retries included), `model` (always the backend's model name, also for cache and fallback), `errors` (every backend or validation error, prefixed with its attempt number) and `no_keyword_match`. Per-attempt backend latencies are in the log.
- **Why:** D-014, D-015, D-016.
- **Alternatives:** retrying backend errors (not asked); reporting `model` as `keyword-table` on fallback (the source field already says it).

### D-112 Keyword table, fallback and E1 baseline
- **Date:** 2026-11-14 | **Status:** Proposed (the table content needs the user's review)
- **Decision:** `configs/keyword_rooms.json` has entries of `keywords`, `targets` and a `room_prior` over the six room IDs. It has one entry for each of the 12 vocabulary classes plus categories: food (food, eat, hungry, snack, fruit to banana, apple, orange, sandwich), drink (cup, bottle), electronics (laptop, remote, cell phone), toy (teddy bear), reading (book). Priors are plausible-room guesses (kitchen and dining for food and drink, living room and bedrooms for books and electronics, bedrooms for the teddy bear). Matching is case-insensitive on whole words (an optional plural `s` or `es` is allowed; `cupboard` does not match `cup`). All matched entries combine: targets in order of appearance in the command, prior averaged, then validated, normalized and floored with the same validator as LLM output. With no match: all vocabulary classes as targets, a uniform prior, `no_keyword_match` true. Entries whose targets are not in the current vocabulary are skipped. `keyword_ground()` and `check_keyword_table()` work without any backend, so the same table is the E1 keyword baseline. `room_constraint` is always null (the baseline ignores relational commands).
- **Why:** D-014 (fallback table, also an E1 baseline); class names live in the config, not in code.
- **Alternatives:** first match only (loses multi-object commands); embeddings (not a keyword baseline).

### D-113 Cache
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** One JSON file per key in the cache directory, written atomically. Key = SHA-256 of: the normalized command (whitespace collapsed, case folded), the scene graph (full dump but without `viewpoints`, since they never reach the prompt, D-047), the vocabulary (order-sensitive), the model name, the fully rendered system prompt (so template, few-shot examples, graph text and vocabulary edits all invalidate it), and the validator floor (it changes the stored prior). Only validated results from the backend are stored; fallback results never are. A missing or corrupt file is a miss.
- **Why:** D-016, plus the requirement that prompt edits invalidate cached answers.
- **Alternatives:** hashing the full graph including viewpoints (regenerating viewpoints would throw away valid answers); keying only on the command (stale after any change).

### D-114 JSONL log
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** One line per `ground()` call (cache hits and fallbacks included) with `timestamp` (UTC), `command`, `model`, `cache_hit`, `source`, `attempts`, `latency_s`, `backend_latencies_s`, `raw_responses`, `validation_errors` (per attempt), `backend_errors`, `no_keyword_match` and the final `result`. The API key is never part of a record; as a safeguard, any string equal to the `GEMINI_API_KEY` value (read at write time) is replaced by `[REDACTED]`. The log directory is created on demand.
- **Why:** D-016 (the log is the E1 data); the result is included so E1 scoring does not need to re-run anything.
- **Alternatives:** logging only metadata (cannot reproduce E1 failures).

### D-115 CLI
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `python -m lang_grounding.ground "<command>" --backend gemini|ollama|fake` (default `fake`, so a bare call never uses the network) prints the outcome as JSON. Options: `--config`, `--graph`, `--vocabulary`, `--no-cache`, `--no-log`. Defaults use the real `data/scene_graph.json` and the files named in the config. Configuration, scene graph, vocabulary and empty-command errors print `ERROR: ...` to stderr and exit 2.
- **Why:** quick manual check and demo of each backend.
- **Alternatives:** human-readable output (harder to script).

### D-116 Prompt builder follows the real prompt files (amends D-110)
- **Date:** 2026-11-15 | **Status:** Agreed
- **Decision:** The builder was changed to match the user's `configs/prompts/system.md` and `fewshot.json` (the files are not edited). The system template must contain `{scene_graph}` and `{vocabulary}`; `{examples}` is now optional. When the template has no `{examples}`, the few-shot examples are appended to the end of the filled system prompt under a heading `## Examples` plus one line ("Each example shows a command and the complete JSON response expected for it."), then each example as `Example N`, `Command: ...`, `Response: <JSON>`; with no examples nothing is appended. `fewshot.json` is a JSON list of `{command, response}` objects, or (amended 2026-11-15, after the user's file changed to this layout) an object `{"examples": [...]}` holding that list; both are accepted, and `response` is the full expected JSON output. An empty list is allowed. The cache key uses the rendered system prompt, so it still changes when the examples change (D-113).
- **Why:** the user's files define the format; the backend interface carries only a system and a user prompt, so the examples stay in the system prompt.
- **Alternatives:** editing the user's files to add `{examples}` (not allowed); sending the examples as chat turns (needs a message list in the backend interface); appending them without a heading (the model could not tell where the rules end).

### D-117 E1 command file and its automated checks
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `data/e1_commands.json` holds the E1 commands (`id`, `type` of explicit, category, need or relational, `command`, `expected_constraint` as a list of room IDs or null). Tests in `tests/test_e1_data.py` check: (1) D-017: no few-shot command equals an E1 command after lowercasing, removing punctuation and collapsing whitespace, and none has a token-set Jaccard similarity of 0.6 or more with one, after removing a fixed list of English stop words (the threshold is inclusive); (2) every vocabulary class is named in at least one E1 command (whole word or phrase, optional plural `s`/`es`); (3) every `expected_constraint` room ID exists in `data/scene_graph.json`. A further test checks that every few-shot response passes the validator against `data/scene_graph.json` and `configs/vocabulary.json`. The checking helpers live in the test file, not in the package.
- **Why:** D-017 must be enforced by a check, not by memory; the other checks catch typos and coverage gaps in the test set.
- **Alternatives:** a similarity measure over embeddings (not deterministic, extra dependency); exact-match only (misses reworded duplicates).

### D-118 E1 plausibility labels
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** E1 labels live in `data/e1_labels_<person>.csv`, one file per labeler, with the columns `id, command, E, K, LR, D, B1, B2, notes`; a room column holds 1 if the room is plausible for the command and is empty or 0 otherwise. For commands that name or describe rooms, only rooms that satisfy the description may be labeled plausible. `expected_constraint` in `e1_commands.json` follows D-002 (neighbors are door-connected).
- **Why:** labels are made independently and then reconciled; one fixed format makes them comparable and scriptable, and the room-description rule keeps labels consistent with the constraint the grounding is supposed to produce.
- **Alternatives:** labels inside `e1_commands.json` (an earlier draft; separate files keep the two labelers independent).

### D-119 E1 set: strict vocabulary coverage, 39 commands
- **Date:** 2026-11-15 | **Status:** Agreed
- **Decision:** Every vocabulary class must be named (as a word or phrase, optional plural) by at least one command in `data/e1_commands.json`; the test `test_every_vocabulary_class_appears_in_an_e1_command` stays strict, with no allowance for classes that are only implied by a category command. The E1 set is now 39 commands (the original 36 plus explicit commands for apple, sandwich and bowl). The count is recorded here for reference only: no test or document asserts it, so adding or removing a command needs no test change.
- **Why:** an E1 set that never names a class cannot show whether the grounding handles it; the explicit commands close the gap found by the coverage test (D-117).
- **Alternatives:** counting implied coverage through category commands (cannot be checked automatically); asserting the exact count in a test (breaks on every edit of the set).

### D-120 `.env` loader (amends D-105)
- **Date:** 2026-11-15 | **Status:** Agreed
- **Decision:** `src/lang_grounding/env.py` provides `load_env_file(path=None)` (standard library only). It reads `NAME=value` lines; blank lines and full-line `#` comments are ignored; an optional `export ` prefix is accepted; matching single or double quotes around a value are removed (no escape processing); an unquoted value ends at whitespace followed by `#` (inline comment); there is no variable expansion; a value may contain `=`. Variables already set in the environment are never overridden (even if set to an empty string); within one file a later line for the same name wins. A missing file is not an error. A malformed line (no `=`, invalid name, unterminated quote, text after a closing quote) raises `ConfigError` naming the file and line number only: the message never contains the line, the name or the value, since a malformed line can be a secret pasted without its name. The whole file is parsed before anything is set, so a malformed file changes nothing. The default file is `.env` at the repository root; a relative `--env-file` path is relative to the repository root too (as in D-105). `load_config()` calls the loader first (so library users and the CLI both get it), and the CLI passes `--env-file`. `tests/conftest.py` redirects the default path during tests so that a developer's real `.env` is never read by the test suite.
- **Why:** removes the manual export step without adding python-dotenv; keeping secrets out of error messages matters because the file holds the API key.
- **Alternatives:** python-dotenv (extra dependency, more features than needed); loading only in the CLI (library callers would still need exports); letting `.env` override the shell (surprising, and makes one-off overrides impossible).

### D-121 E1 label tool: validation and comparison
- **Date:** 2026-11-15 | **Status:** Agreed
- **Decision:** `src/lang_grounding/e1_labels.py` (pure Python) with `python -m lang_grounding.e1_labels validate <file>` and `compare <A> <B>`; options `--commands` (default `data/e1_commands.json`) and `--graph` (default from the config). A label CSV needs the columns `id`, `command` and exactly the scene graph's room IDs (any order); `notes` is optional; any other column, a duplicate column, or an empty file is an error. Cells are read with whitespace stripped. **Errors:** a command ID without a row, an unknown ID (wrong ID), a duplicate row, a command text that differs from `e1_commands.json` (compared after collapsing whitespace, case-sensitive), a cell other than `1` or blank, a row with no room labeled, a row with more cells than the header, and a labeled room outside `expected_constraint` (the message names the room and says that "next to" means connected by a door, D-002, and that rooms that only share a wall do not count). **Warning, not error:** more than 3 rooms labeled in a row. `compare` first validates both files and refuses to compare if either has errors; it then reports overall cell agreement (agreeing room cells over commands times rooms), the per-command Jaccard (and its mean, and the number of identical commands), and a table of the disagreeing commands (id, command, rooms only in A, rooms only in B, Jaccard). Neither command writes any file. Exit codes: 0 fine (warnings allowed), 1 a label file is invalid or unreadable, 2 the command file or scene graph cannot be loaded.
- **Why:** D-118 (one label file per labeler, then reconciled) needs a check that catches typos and violations of the room-description rule before agreement is computed, and the comparison feeds the reconciliation.
- **Alternatives:** an `id`-only match without the command text (misses rows pasted in the wrong order); treating more than 3 rooms as an error (the guideline is "aim for", not a limit); computing agreement with Cohen's kappa (cells are mostly blank, so kappa is unstable here; raw agreement plus Jaccard is easier to read).

### D-122 E1 labeling guideline and reconciled file
- **Date:** 2026-11-15 | **Status:** Agreed
- **Decision:** A room is labeled plausible (`1`) where you would expect the object in an ordinary home, not merely where it could be; aim for 1 to 3 rooms per command. For category and need commands, the labels are the union of the rooms of all matching objects. For relational commands, the labels are that union restricted to the rooms the description allows (`expected_constraint`, D-002), or the allowed rooms themselves if the union and the allowed rooms do not overlap. The reconciled labels, after the two labelers compare their files, are `data/e1_labels_final.csv` (same format as D-118).
- **Why:** consistent labels across labelers and command types; the restriction keeps relational labels in line with the constraint the grounding is supposed to produce (D-118).
- **Alternatives:** labeling every room where the object could possibly be (nearly every room, so the labels would say little); a separate file per command type (harder to compare).

### D-123 `GroundOutcome` reports the fallback reason and the backend latency
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `GroundOutcome` has two new fields, also in `to_dict()` and in every JSONL log record: `fallback_reason` (only when `source` is `fallback`: `backend_error` if the last thing that happened was a backend error of any kind, including a malformed response envelope or a backend error during the retry; `invalid_output` if the backend answered twice and both answers failed validation) and `backend_latency_s` (only for `source` `llm`: the backend latency of the successful attempt, without a failed first attempt). `latency_s` stays the wall-clock time of the whole call. Cache hits have neither. The validator and the flow of `ground()` are unchanged.
- **Why:** E1 must re-run commands that failed for backend reasons but count invalid output as a real LLM failure, and it must report the latency of the answer itself, not of the retries.
- **Alternatives:** parsing the `errors` strings (fragile); summing or averaging the per-attempt latencies (mixes failed and successful calls).

### D-124 `names_only` scene-graph rendering (the E1 ablation)
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `PromptBuilder` has a `scene_graph_style`, `"full"` (default, the existing `render_for_prompt`, unchanged) or `"names_only"` (new `render_names_only`), selected with `PromptBuilder.with_scene_graph_style()`. `names_only` renders "The building has N rooms:" and one `- ID: name` line per room: no areas, no doors or adjacency, no exterior-door note, and no definition of "next to". Everything else in the system prompt (the template text, vocabulary, few-shot examples) is the same, so the ablation changes only the building description. The few-shot examples are not changed for the ablation, so they still show the answers for the real layout.
- **Why:** the proposal's E1 ablation (the LLM with and without the scene graph).
- **Alternatives:** dropping the building description entirely (the model would not even know the room IDs); also removing adjacency text from the template (would change the template, not just the description).

### D-125 E1 methods, scoring and aggregation
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** `src/lang_grounding/e1.py`, CLI `python -m lang_grounding.e1 run`. Methods: `keyword` (the keyword table, no backend), `uniform` (equal prior), and `gemini_full`, `gemini_names_only`, `ollama_full`, `ollama_names_only`; the order given is the order run. Inputs: `data/e1_commands.json` and `--labels` (default `data/e1_labels_final.csv`); the label validator (D-121) runs first and the experiment refuses to run, writing nothing, if it reports errors (warnings are printed). Scoring per command and method: rooms ranked by `room_prior`; top-1 hit = the top room is labeled plausible; top-2 hit = at least one of the top two is. Tied rooms at the cut-off are scored with the expected value under random tie-breaking, in one function (`topk_hit`; ties within 1e-9): a uniform prior with 2 labeled rooms of 6 scores 2/6 for top-1 and 0.6 for top-2. Constraint check, LLM methods only: for a command with an `expected_constraint`, the LLM's `room_constraint` must equal it as a set; for any other command it must be null. Both rates are reported ("constraint match" and "constraint null"). Latency is the backend latency of the successful attempt (D-123). Aggregates per method, overall and per command type: top-1, top-2, both constraint rates, mean, median and p95 latency (linear interpolation, answered commands only), number of fallback rows, and number and rate of invalid-output rows. A command that never gets an LLM answer (invalid output, or backend errors through the last pass) is a miss in every rate, and is listed separately; the keyword-fallback result of such a call is never scored as an LLM result (its row has no ranking, targets or latency). The summary also has a full-versus-names-only table per provider and a hosted-versus-local latency table (all answered calls of a provider pooled).
- **Why:** the E1 definition in the proposal, with misses counted honestly; expected-value tie handling makes the uniform baseline well defined.
- **Alternatives:** breaking ties by room order (would make the uniform baseline depend on the order of the room list); counting fallback results as LLM answers (hides LLM failures).

### D-126 Pacing, re-runs and the cache in E1
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** E1 LLM runs never read or write the cache (`ground()` is called with `cache=None`), so latency is real. Calls to one provider start at least `--min-interval-s` (default 6) apart, tracked per provider and counted from the start of the previous call (a slow call already used up the wait); the clock and the sleep function are injectable. If `ground()` returns a fallback with `fallback_reason` `backend_error` (timeout, rate limit, network, malformed response), the command is re-run after a wait of `--backoff-s` (default 30, my choice) doubled for every further pass, up to `--max-passes` (default 3) passes in total. A fallback with `invalid_output` is not re-run: it is a real LLM failure, counted as a miss and reported through the invalid-output rate. Passes are visible in the per-command CSV and in `calls.jsonl`. With `--dry-run` there is no waiting.
- **Why:** the Gemini free tier limits the request rate; re-running only transport failures keeps the LLM's own mistakes in the results.
- **Alternatives:** pacing all providers together (would slow the local model for no reason); re-running invalid output (would hide an unreliable model).

### D-127 E1 outputs and dry run
- **Date:** 2026-11-15 | **Status:** Proposed
- **Decision:** Each run writes `results/e1/<UTC timestamp>/` (`--out-dir` changes the parent; the folder is meant to be tracked in git): `calls.jsonl` (one record per call, written as the run goes: the `ground()` log record, with raw responses and validation errors, plus the method, command ID, type and pass; baseline rows are included), `per_command.csv` (columns id, type, method, source, attempts, top1, top2, constraint_ok, latency_s, ranked_rooms, targets, rationale, and two extra columns, fallback_reason and passes; fractional top-1/top-2 values are tie scores), `summary.md` (the tables above, the settings, the models used, the commands without an LLM answer, and the scoring rules) and `failures.md` (every top-1 miss with the command, the labeled rooms, the ranking with probabilities, the rationale, a constraint mismatch if any, or the reason there was no LLM answer). The paths are printed at the end. `--dry-run` replaces the LLM backends by the fake backend and says "DRY RUN" in the summary; it is for checking the pipeline and its numbers mean nothing. Exit codes: 0 done, 1 the label file failed validation, 2 setup or option errors.
- **Why:** the outputs named in the E1 request; a log written as the run goes survives an interrupted run.
- **Alternatives:** one summary file only (no data for the failure analysis); writing the CSV incrementally too (only `calls.jsonl` is, to keep the writing simple).

## Open points to confirm with Kristika
None at the moment. Former points 1–4 were answered by D-050, D-006, D-007 and D-074.

## Decision history
- 2026-11-16: Touch acceptance run (D-094) on the demo scenario: 11/12 passed against Gazebo truth (true gaps 0.046–0.048 m on the gap stop, 0.135–0.136 m on the depth stop, cell phone 0.000 m). The cup failed with 0 sightings and a false `gap` success; D-098 amended: whole-width first search and an `unseen` failure.
- 2026-11-16: Step 7 verified in Gazebo (bottle true gap 0.136 m on the depth stop, banana ~0.047 m on the gap stop). Phase 3 step 8: D-093 (one-command trial launch) and D-094 (touch acceptance against Gazebo ground truth) proposed.
- 2026-11-16: D-098 revised (floor-filtered depth tracking in the odom frame; depth stop 0.14 m) and D-099 updated after the Gazebo runs: depth showed the floor, and AMCL was 4–11 cm off at the targets.
- 2026-11-15: Phase 3 step 7 (approach and touch) decisions D-098, D-099 proposed. D-097 verified in Gazebo (center depth 1.507 m against 1.51 m expected).
- 2026-11-15: D-097 (depth camera, new topics `/camera/depth/image_raw` and `/camera/depth/camera_info`) proposed. Step 6 verified in Gazebo (bumper contacts with `obj_bottle_0` and a wall).
- 2026-11-15: D-116, D-119, D-120, D-121 and D-122 set to Agreed. The vocabulary note in D-100 fixed (the catalog now has all 12 classes).
- 2026-11-15: E1 experiment runner (D-125 to D-127), the `names_only` ablation rendering (D-124) and the fallback reason and backend latency fields (D-123) proposed.
- 2026-11-15: D-107 set to Agreed (Gemini schema conversion verified live with one easy command; relational commands, retries and free-tier rate limits still untested). E1 label tool (D-121) and labeling guideline (D-122) proposed.
- 2026-11-15: E1 set is 39 commands with strict vocabulary coverage (D-119); `.env` is now read automatically by a standard-library loader (D-120, amends the ".env is not read" sentence in D-105). Both Proposed.
- 2026-11-15: D-004 and D-005 set to Agreed (Kristika confirmed on Nov 15 that the planner uses `room_prior` only and that the detector computes `room_id`). Prompt builder amended to the real prompt files (D-116). E1 command checks (D-117) and E1 label format (D-118) proposed.
- 2026-11-15: Phase 3 step 6 (contact sensor) decisions D-095, D-096 proposed. Found: the simulated Waffle camera is RGB only (no depth), although the proposal assumes RGB-D.
- 2026-11-15: Kristika's answers to Ansh's interface questions: D-006 (planner uses `room_prior` only) and D-007 (detector computes `room_id`) agreed; D-074 (oracle truth files `data/objects_<scenario>.json`) agreed; open points 2–4 closed. D-051 to D-092 promoted to Agreed by Kristika. D-070 updated: catalog extended to the 12-class vocabulary (orange, bowl, cell phone added), so the vocabulary note in D-100 is resolved.
- 2026-11-14: Phase 4 grounding loop, backends, cache and logging (D-104 to D-115) proposed. Prompt files and the keyword table are placeholders or drafts awaiting the user's text and review.
- 2026-11-14: D-003, D-020, D-022, D-046 set to Agreed. D-014 wording updated to match D-103 (floored rooms held exactly at the floor; status unchanged). D-047 (optional `viewpoints` field with point-in-polygon check) proposed. Log entries put in numeric order.
- 2026-11-14: Phase 4 grounding output schema and validator (D-100 to D-103) proposed.
- 2026-11-14: Phase 3 step 5 (clutter) decisions D-090 to D-092 proposed. Step 4 verified (viewpoints E 1, K 2, LR 2, D 1, B1 2, B2 2).
- 2026-11-14: Phase 3 step 4 (search viewpoints) decisions D-080, D-081 proposed. Step 3 verified in Gazebo (objects on the floor, clear of doorways, robot stops on contact).
- 2026-11-14: Phase 3 step 3 (target objects) decisions D-070 to D-073 proposed; open point 4 (oracle ground-truth source) added. Step 2 verified: room tour reached all 6 rooms.
- 2026-11-13: Phase 3 step 2 (AMCL + Nav2) decisions D-060 to D-064 proposed. Step 1 verified in Gazebo (spawn in E, lidar, E-K door, closed exterior door).
- 2026-11-13: D-050 (map frame = Gazebo world frame, origin at the bottom-left outer corner, map yaml origin [-margin, -margin, 0]) agreed; open point 1 closed. Phase 3 simulated house decisions D-051 to D-057 proposed.
- 2026-11-12: Phase 1 scene graph implementation (D-040 to D-045) proposed.
- 2026-11-12: Phase 2 skeleton (D-030, D-031) proposed.
- 2026-11-12: Phase 1 started (D-020 to D-022); Phase 0 started; D-001, D-002 agreed; D-003 to D-005 proposed; grounding node decisions D-010 to D-017 recorded from the design discussion.
