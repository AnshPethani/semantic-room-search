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

## Phase 3: Simulated house (Kristika, step 1)

### D-050 Map frame (answers former open point 1)
- **Date:** 2026-11-13 | **Status:** Agreed
- **Decision:** The Nav2 `map` frame equals the Gazebo world frame of `house_sim`. Origin at the bottom-left outer corner of the house, x to the right, y up, meters. The map yaml origin is `[-margin, -margin, 0]` (margin 0.5 m in the layout, so `[-0.5, -0.5, 0.0]`), i.e. the bottom-left pixel of the map image starts at (-margin, -margin).
- **Why:** set by Kristika's world; it is the same convention as the placeholder (D-020), so the scene graph, the map and Gazebo share coordinates with no extra transform.
- **Alternatives:** map origin at the image corner with a separate map-to-world transform (one more TF to keep in sync).

### D-051 Room polygons are the layout source of truth; floor rectangles are derived
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** In `layout/house_layout.yaml` each room is a counter-clockwise polygon on wall center-lines (so a door lies on the boundary of both rooms it connects), with axis-aligned edges only. LR is the 6-vertex L shape. The generator derives the Gazebo floor tiles by vertical-strip decomposition (cut at every vertex x; inside a strip, pair the crossing horizontal edges in y order). The map does not need room rectangles (the house footprint is filled free, then walls are drawn occupied). The generator rejects non-axis-aligned or clockwise polygons; a test checks that the derived rectangles cover each polygon exactly.
- **Why:** one room format, the one the scene graph needs; derived rectangles cannot drift from the polygons.
- **Alternatives:** keep rectangle lists and compute polygons from their union (harder, and the L-shape vertex order would be implicit); list polygons and rectangles separately with a coverage test (two things to edit); allow arbitrary polygons (not needed for this house, and floor tiles would need triangulation).

### D-052 Exterior door `d_E_out` is closed in the simulation
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** `d_E_out` (between E and `outside`) is at (1.8, 9.0) on E's north outer wall, 1.0 m wide; the position is taken from the placeholder (D-020). The scene graph lists it as a normal door. In Gazebo the gap is filled with a static, door-colored (brown) panel with collision, in model `house_doors`, link `door_d_E_out`: length = width - wall thickness (the clear opening between the wall ends), thickness = wall thickness, height = wall height. On the map the panel is occupied. Rule: every door to `outside` is generated closed (no per-door flag).
- **Why:** D-002 requires the exterior door in the scene graph, but the robot must not be able to leave the house or plan through it.
- **Alternatives:** leave it out of the world (world and scene graph disagree); open door (robot and Nav2 can leave the house); explicit `closed: true` flag per door (unnecessary while the only exterior door is always closed).

### D-053 Door IDs and door data
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** Door IDs are derived from the layout's `connects` pair as `d_<A>_<B>`, in the listed order, with `outside` written as `out` as in the spec example (giving d_E_LR, d_E_K, d_K_LR, d_LR_D, d_LR_B1, d_LR_B2, d_E_out, the same IDs as the placeholder). The door `center` must lie on a wall center-line, and its whole width must lie on one wall segment (the generator rejects it otherwise). Door width stays in the layout only; the scene graph keeps the spec fields `id`, `between`, `position`. Note: wall pieces are extended by half the wall thickness at both ends (unchanged existing behavior), so the clear opening is width - 0.15 m (0.85 m, or 1.25 m for d_LR_D).
- **Why:** one source for IDs; the spec format stays unchanged.
- **Alternatives:** explicit IDs in the layout (a second value that can disagree with `connects`).

### D-054 Generated scene graph file
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** The generator writes `data/scene_graph.json` at the repository root in the "Interface specs" format. Rooms appear in D-001 order (E, K, LR, D, B1, B2), doors in layout order. Polygons are copied from the layout; `area` (shoelace) and `centroid` (area centroid) are computed by the generator and rounded to 4 decimals (well inside the loader's 0.05 tolerance). Format: 2-space indented JSON with each coordinate pair and each `between` pair on one line, LF line endings, trailing newline. All generated files are written as bytes, so the output is identical on Linux and Windows. The centroid of a non-convex room is not guaranteed to lie inside it (for the current LR it does); code that uses centroids as navigation goals must check this.
- **Why:** Ansh's loader consumes it unchanged; stable formatting makes the drift test byte-exact.
- **Alternatives:** write into the ROS package and copy (two copies); full precision floats (noisy diffs such as 16.169999999999998).

### D-055 `config/rooms.yaml` removed
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** `config/rooms.yaml` is no longer generated and is deleted. Its rooms, areas, centroids, doors and door adjacency are in `data/scene_graph.json`. The launch file now reads `robot_start` from `layout/house_layout.yaml`. Dropped fields: `rects` (derivable, D-051), `shares_wall_with` (not used under D-002), door `width` (stays in the layout). `CMakeLists.txt` no longer installs `config/`. A test checks the file stays gone.
- **Why:** two room formats would drift apart.
- **Alternatives:** keep it and add a test that it agrees with the scene graph (more to maintain, no consumer needs it).

### D-056 Generator location and test import
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** The generator stays at `ros/house_sim/scripts/generate_house.py` (the package root is `ros/house_sim/`, flattened from the earlier nested `ros/house_sim/house_sim/` on 2026-11-13), next to the layout and the outputs it owns. It has no ROS imports (standard library + PyYAML; Pillow only for `--preview`). `tests/test_house_sim.py` loads it by file path with `importlib`, so plain `pytest` runs it without ROS sourced and without installing anything new. `pyyaml>=6` is added to the `dev` extras in `pyproject.toml`.
- **Why:** keeps simulation code out of `lang_grounding` and keeps the ROS package self-contained, while the tests stay ROS-free.
- **Alternatives:** move it into `src/lang_grounding` (mixes world generation into the grounding library); a second installable package under `src/` (more packaging for one script); pytest `pythonpath` setting (puts the scripts folder on the import path of every test).

### D-057 Drift test
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** A test generates into a temporary directory and compares byte-for-byte with the committed `worlds/house.sdf`, `maps/house_map.pgm`, `maps/house_map.yaml` and `data/scene_graph.json`. Text files are compared after converting CRLF to LF (so a Windows checkout with `core.autocrlf` passes); the PGM is compared exactly. `maps/house_map_preview.png` is excluded: Pillow output is not guaranteed byte-stable across versions, and the preview is a visual aid only.
- **Why:** committed outputs can never silently disagree with the layout.
- **Alternatives:** do not commit generated files (the ROS build and Ansh's tests would then depend on running the generator first).

## Phase 3 (continued): AMCL + Nav2 on the known map (Kristika, step 2)

### D-060 Navigation launch structure
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** `ros/house_sim/launch/house_nav.launch.py` includes `house_world.launch.py` (Gazebo + robot at `robot_start`), `nav2_bringup/bringup_launch.py` (map_server with `maps/house_map.yaml`, AMCL, planner, controller, behaviors, BT navigator; `use_sim_time:=true`, `autostart:=true`) and, optionally, `nav2_bringup/rviz_launch.py`. Arguments: `gui`, `rviz`. No SLAM. Nav2 is used as shipped; only its parameters are changed (D-061).
- **Why:** smallest launch that gives localization and navigation on the known map; reuses the maintained Nav2 bringup instead of re-listing its nodes.
- **Alternatives:** own launch listing every Nav2 node (more code, easy to miss a lifecycle node); `nav2_bringup/tb3_simulation_launch.py` (starts its own world and robot).

### D-061 Nav2 parameters: committed copy of the Jazzy default with marked edits
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** `ros/house_sim/config/nav2_params.yaml` is a copy of `/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml`, committed to the repo. Every change made for this house is marked with a `# house_sim:` comment, and a ROS-free test checks the edited values. The edits are made after the copy exists, so they start from the real installed default. Edits so far (base: nav2_bringup 1.3.13): AMCL `set_initial_pose`/`initial_pose` (D-062) and `laser_max_range` 3.5 (TurtleBot3 LDS); MPPI `vx_max`/`vx_min` ±0.26 and `wz_max` 1.82, and velocity smoother limits [±0.26, 0, ±1.82] (Waffle limits; the default 0.5 m/s makes MPPI plan for speeds the robot cannot reach); `enable_stamped_cmd_vel: true` on every node that publishes velocity (the TurtleBot3 Jazzy bridge takes TwistStamped on `/cmd_vel`). Unchanged on purpose: `robot_radius` 0.22, inflation radius 0.7 and cost scaling 3.0 (the narrowest clear opening, 0.85 m, still leaves a 0.35 m corridor for the robot center); tuning comes with the clutter step.
- **Why:** reproducible (the file used in experiments is versioned); later tuning (inflation, MPPI or DWB, recoveries; proposal Nov 20–25) edits the same file.
- **Alternatives:** writing the file from scratch (easy to miss a required key, e.g. the Jazzy docking server); rewriting the installed default at launch time with `RewrittenYaml` (small, but the base file can change with a package update, unnoticed).

### D-062 Initial pose comes from the layout
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** AMCL starts at the layout's `robot_start` through `set_initial_pose`/`initial_pose` in `nav2_params.yaml`; a test checks that the two agree. The room tour script also sets the same pose through `BasicNavigator.setInitialPose`, because `waitUntilNav2Active` otherwise republishes a zero initial pose.
- **Why:** the robot is localized at launch without clicking "2D Pose Estimate", and the spawn pose, AMCL and the tour can not disagree.
- **Alternatives:** manual pose estimate in RViz (not repeatable for headless trials).

### D-063 One goal per room for navigation checks
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** `ros/house_sim/scripts/room_goals.py` (ROS-free) picks, for each room polygon, the 0.05 m grid point that is farthest from the polygon boundary (wall center-lines), ties broken by distance to the area centroid. Goals are computed at run time from the layout polygons, not stored. Tests check that every goal is inside its own room only and at least 0.5 m from every wall surface and the closed exterior door.
- **Why:** the centroid of the L-shaped LR is not guaranteed to be inside it (D-054); this point always is, with maximum clearance.
- **Alternatives:** centroids (can fall outside non-convex rooms); hand-picked goals (another list to keep in sync). Viewpoints for the search (proposal Step 2) are a separate later step and may replace these goals.

### D-064 Room tour as the Nav2 acceptance check
- **Date:** 2026-11-13 | **Status:** Proposed
- **Decision:** `ros2 run house_sim room_tour.py` (needs `house_nav.launch.py` running, robot at the start) sends goals to K, LR, D, B2, B1, E in that order with `nav2_simple_commander`, prints the result and time for each room, and exits 1 if any goal fails or times out (default 180 s per goal). This passes through every interior door at least once. It is a manual ROS check, not part of `pytest`.
- **Why:** the proposal's milestone for this step is reliable navigation into every room on the known map.
- **Alternatives:** clicking goals in RViz (not repeatable); a launch_testing test (needs Gazebo in CI, too heavy for now).

## Phase 3 (continued): target objects (Kristika, step 3)

### D-070 Placeholder target objects per COCO class
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `ros/house_sim/objects/catalog.yaml` lists the proposal's target classes, keyed by exact COCO name (banana, apple, sandwich, bottle, cup, book, laptop, remote, teddy bear). Each is a simple shape (box, cylinder or sphere) at about real size with a distinct color. Objects are static models with one collision and one visual, so the robot cannot push them away and the touch step can register contact. Realistic models (Gazebo Fuel where available) replace the shapes with the YOLO switch (proposal Nov 20–25).
- **Why:** the oracle detector (used first) does not need realistic appearance; no dependency on downloading models now.
- **Alternatives:** Fuel models now (network at run time, availability per class not checked yet); dynamic objects (can be pushed or knocked over by the robot, which moves the ground truth).

### D-071 Scenario files
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** A scenario is `ros/house_sim/objects/scenarios/<name>.yaml` with a list of objects: `label` (catalog class), `room`, `xy` (map frame) and `yaw`. The room is stored for readability and for later plausible/implausible bookkeeping, and is checked against the polygons. `demo.yaml` places one object of every class in a plausible room. Per-trial random placement (80% plausible, 20% implausible, fixed seeds) belongs to the evaluation harness and is not part of this step.
- **Why:** a fixed, readable placement for the first end-to-end runs and for Ansh's oracle detector; the harness can later write files in the same format.
- **Alternatives:** objects baked into `house.sdf` (every placement change needs a regenerated world); random placement now (harness work, out of scope).

### D-072 Object placement rules
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** Each object (its footprint circle) must be inside its declared room and at least 0.3 m from wall surfaces and the closed exterior door, 0.5 m from every door gap, 0.6 m from every room tour goal (D-063), 0.8 m from the robot start, and 0.3 m from every other object. `scripts/house_objects.py` checks this before spawning; tests cover each rule.
- **Why:** most objects are lower than the Waffle's lidar plane, so Nav2's costmaps cannot see them; keeping them off doorways, tour goals and the start keeps navigation from driving into them. 0.5 m from doorways is the proposal's clutter rule.
- **Alternatives:** no rules (a placement can block a doorway or sit on a goal); adding the depth camera to the costmap (a Nav2 tuning change for the clutter step).

### D-073 Spawning objects and model names
- **Date:** 2026-11-14 | **Status:** Proposed (model names are an interface with Ansh's oracle detector)
- **Decision:** `ros2 launch house_sim spawn_objects.launch.py scenario:=demo` spawns a scenario into the running world (`house`) with `ros_gz_sim create`, one call per object, after the placement check. Gazebo model names are `obj_<label>_<k>`, with spaces in the label replaced by underscores and `k` counting objects of the same class from 0 (e.g. `obj_teddy_bear_0`); `house_objects.label_from_model_name` maps a name back to the COCO label.
- **Why:** objects change per trial without regenerating the world; the name alone tells the oracle detector the class.
- **Alternatives:** spawning from a Python node through the Gazebo service (more code than the existing `create` tool); names without the class (the oracle would need the scenario file to know the label).

## Phase 3 (continued): search viewpoints (Kristika, step 4)

### D-080 Viewpoints in the scene graph
- **Date:** 2026-11-14 | **Status:** Proposed (adds the optional field the spec reserved; Ansh's loader and schema are unchanged)
- **Decision:** The generator adds `"viewpoints": [[x, y], ...]` to every room in `data/scene_graph.json`: 1–3 map-frame positions, sorted by x then y, rounded to 1 mm. At each viewpoint the robot turns 360°; viewpoints have no heading. The loader already ignores unknown fields (D-042), and the JSON Schema does not forbid extra properties, so the graph still validates. Settings live in a `viewpoints` section of `house_layout.yaml` (camera range, wall clearance, maximum per room, grid sizes). `maps/house_map_preview.png` marks viewpoints as green squares.
- **Why:** the "Interface specs" note reserves this optional field for Kristika's viewpoint generator; one file holds everything the planner needs about rooms.
- **Alternatives:** a separate viewpoints file (another file to keep in sync with the graph); storing the robot heading too (not needed for a 360° turn).
- **For Ansh:** if the planner reads viewpoints through `lang_grounding.scene_graph`, the `Room` model and the schema file need an optional `viewpoints` field and a check that each point is inside its room.

### D-081 Viewpoint coverage model and selection
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** A floor point counts as seen from a viewpoint if it is within `camera_range` (3.0 m) and the straight line to it stays inside the room polygon (matters for the L-shaped LR). Floor points are sampled every 0.2 m, at least 0.05 m beyond the wall surfaces; candidate viewpoints every 0.25 m, at least 0.5 m from wall surfaces so the robot can turn in place. Selection: the fewest viewpoints (up to 3) that see every floor sample; among those, the set that does so with the smallest range (tried in 0.25 m steps up to 3.0 m), so each viewpoint sits near the middle of what it covers; ties go to the set whose viewpoint closest to a wall is farthest from it, then to grid order. Search is exhaustive over candidate sets, so the result is deterministic and the count is minimal on the grid. Result for this house: E 1, K 2, LR 2, D 1, B1 2, B2 2 (10 in total). The generator stops with an error if a room needs more than 3.
- **Why:** follows the proposal ("1–3 viewpoints per room, chosen from its polygon so the camera covers the room during a 360° rotation"); the count feeds the planner's search cost.
- **Assumptions to revisit:** 3.0 m is an assumed detection range for small COCO objects, not measured; occlusion by furniture and clutter is ignored; the camera's minimum range and floor visibility close to the robot are ignored. Tune `camera_range` once the detector is tested.
- **Alternatives:** greedy set cover (fewer computations, but in K it picks the center first and then needs two more viewpoints for the corners: 3 where 2 suffice); fixed viewpoints by hand (another list to keep in sync).

## Phase 3 (continued): clutter (Kristika, step 5)

### D-090 Clutter types
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `ros/house_sim/objects/clutter.yaml` defines three clutter types as static placeholder shapes: box (0.4 m cube), bin (cylinder, 0.15 m radius, 0.5 m tall) and chair (0.45 × 0.45 × 0.85 m box). All are at least 0.3 m tall, above the Waffle's lidar plane, so Nav2's obstacle layers see them. Clutter is never written to the static map. Gazebo model names are `clutter_<type>_<k>`.
- **Why:** proposal Step 3 ("boxes, chairs, bins", only in the costmaps through the lidar); static so a collision cannot push clutter out of the way unnoticed.
- **Alternatives:** Fuel furniture models (later, with the realistic target models); dynamic clutter (pushable, changes the trial).

### D-091 Clutter placement rules and reachability check
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** Each clutter object (footprint circle) must be inside a room and at least 0.15 m from walls, 0.5 m from every door gap (proposal), 0.5 m from every viewpoint and room tour goal (the robot stops and turns there), 0.8 m from the start, 0.6 m from target objects, and 0.3 m from other clutter. In addition, after each object is placed, a flood fill on a 0.1 m grid (robot radius 0.22 m, the Nav2 value, plus 0.03 m margin) checks that every viewpoint and room tour goal is still reachable from the start, and that every target still has a reachable cell within 0.7 m; a candidate that breaks this is rejected.
- **Why:** proposal: "kept at least 0.5 m from doorways, so no room becomes unreachable"; the door rule alone does not guarantee this (clutter could close off part of a room or a viewpoint), the flood fill does.
- **Consequence:** viewpoints are never blocked, so the proposal's recovery case "viewpoint blocked: try the next viewpoint, then skip the room" is not exercised by placed clutter. Narrow passages between clutter can still be costly for Nav2.
- **Alternatives:** only the doorway rule (rooms can be cut off); allowing clutter on viewpoints (exercises recovery, but makes success rates depend on placement luck).

### D-092 Random, seeded clutter spawning
- **Date:** 2026-11-14 | **Status:** Proposed
- **Decision:** `scripts/clutter.py` (ROS-free) draws positions uniformly over the house footprint, a type uniformly from the catalog and a uniform yaw from `random.Random(seed)`, and rejects candidates that break D-091 (up to 1000 tries per object, then an error). The same count and seed give the same placement. `ros2 launch house_sim spawn_clutter.launch.py count:=N seed:=S scenario:=demo` spawns 0–10 objects into the running world and logs where they went; `scenario` names the target objects to keep clear of (`none` for no targets). Collision counting from Gazebo contact events and the per-trial seed list belong to the evaluation harness.
- **Why:** proposal: "0–10 clutter objects spawned at random free locations", "fixed seed list, so every method sees identical conditions".
- **Alternatives:** hand-made clutter scenarios (not random); sampling per room (uneven density in small rooms).

## Open points to confirm with Kristika
2. Whether the planner uses `room_prior` only (proposed) and treats `room_constraint` as informational.
3. Whether `room_id` in the detection message is computed by the detector node (proposed) or by the planner.
4. Where the oracle detector gets object ground truth (to agree with Ansh): object poses from Gazebo (bridging the world's pose topic, with labels from the `obj_<label>_<k>` model names, D-073), or the scenario file directly (valid while objects are static).

## Decision history
- 2026-11-14: Phase 3 step 5 (clutter) decisions D-090 to D-092 proposed. Step 4 verified (viewpoints E 1, K 2, LR 2, D 1, B1 2, B2 2).
- 2026-11-14: Phase 3 step 4 (search viewpoints) decisions D-080, D-081 proposed. Step 3 verified in Gazebo (objects on the floor, clear of doorways, robot stops on contact).
- 2026-11-14: Phase 3 step 3 (target objects) decisions D-070 to D-073 proposed; open point 4 (oracle ground-truth source) added. Step 2 verified: room tour reached all 6 rooms.
- 2026-11-13: Phase 3 step 2 (AMCL + Nav2) decisions D-060 to D-064 proposed. Step 1 verified in Gazebo (spawn in E, lidar, E-K door, closed exterior door).
- 2026-11-13: D-050 (map frame = Gazebo world frame, origin at the bottom-left outer corner, map yaml origin [-margin, -margin, 0]) agreed; open point 1 closed. Phase 3 simulated house decisions D-051 to D-057 proposed.
- 2026-11-12: Phase 1 scene graph implementation (D-040 to D-045) proposed.
- 2026-11-12: Phase 2 skeleton (D-030, D-031) proposed.
- 2026-11-12: Phase 1 started (D-020 to D-022); Phase 0 started; D-001, D-002 agreed; D-003 to D-005 proposed; grounding node decisions D-010 to D-017 recorded from the design discussion.
