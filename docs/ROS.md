# ROS 2 interfaces and the grounding service

Two packages under `ros/` (decisions D-128 to D-132 in [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md)):

- `semantic_msgs` (ament_cmake): `msg/RoomProb`, `msg/Detection`, `srv/GroundCommand`.
- `lang_grounding_ros` (ament_python): the `/ground_command` service node, a thin wrapper. It
  contains no grounding logic; everything comes from the pure-Python library in `src/lang_grounding`
  (which never imports ROS, D-010).

## The service

`/ground_command` (`semantic_msgs/srv/GroundCommand`)

| Field | Meaning |
|---|---|
| request `command` | the natural-language command |
| `success` | false only if no usable answer exists: library exception, timeout, empty command |
| `error` | short one-line reason when `success` is false, else empty |
| `targets` | detector classes, most likely first |
| `room_prior` | `RoomProb[]` (`room_id`, `prob`), one per room, sums to 1 |
| `room_constraint` | room IDs the command is limited to; empty means none |
| `rationale`, `model`, `latency_s` | for logs |
| `cache_hit` | true if the answer came from the on-disk cache |
| `source` | `llm`, `cache` or `fallback` (keyword table); **new, awaiting Kristika's confirmation (D-128)** |

A keyword-fallback answer (the LLM failed or answered invalidly twice) is still `success: true` with
`source: fallback`, so the planner always gets a prior. `success: false` means there is no prior.

## One-time setup (pixi / RoboStack environment)

The ROS environment is separate from the repository's Python 3.12 `.venv`, and the node imports the
library from the repository. Replace `<repo>` with the path of this repository.

1. Open the pixi shell of the ROS environment, then check the Python version of that environment:
   `python --version`. The library declares `requires-python >= 3.12` for the `.venv`; the node
   uses `PYTHONPATH` instead of installing the package, so that declaration is not checked. If
   the environment has an older Python and the import fails with a syntax error, tell me which
   version it is.
2. The library needs pydantic (the only dependency besides the standard library). In the pixi
   environment: `pixi add pydantic` (or `pip install pydantic`). PyYAML is already part of ROS.
3. Build the two packages from the repository root (so that colcon finds `ros/`):
   ```
   cd <repo>
   colcon build --symlink-install --base-paths ros --packages-select semantic_msgs lang_grounding_ros
   source install/setup.bash        # install/setup.zsh in zsh
   ```
   Use `--symlink-install`: the launch file finds the repository through the link.
4. Put the API key in `<repo>/.env` (see `.env.example`). The node reads it with the library's own
   loader (parameter `env_file`); nothing needs to be exported.

## Run

```
ros2 launch lang_grounding_ros ground_command.launch.py                  # Gemini (default)
ros2 launch lang_grounding_ros ground_command.launch.py backend:=ollama
ros2 launch lang_grounding_ros ground_command.launch.py backend:=fake    # offline check
```

The launch file sets `PYTHONPATH` to `<repo>/src` for the node, so the library is found. With
`ros2 run` you set it yourself:

```
export PYTHONPATH=<repo>/src:$PYTHONPATH
ros2 run lang_grounding_ros ground_command_node --ros-args -p backend:=fake
```

Call it (offline check with `backend:=fake`):

```
ros2 service call /ground_command semantic_msgs/srv/GroundCommand "{command: 'find the banana'}"
```

## Parameters

| Parameter | Default (launch) | Meaning |
|---|---|---|
| `scene_graph_file` | `<repo>/data/scene_graph.json` | scene graph, loaded once at start |
| `vocabulary_file` | `<repo>/configs/vocabulary.json` | detector classes |
| `config_file` | `<repo>/configs/grounding.json` | models, timeouts, paths |
| `env_file` | `<repo>/.env` | read with the library's loader; the shell wins over the file |
| `log_dir` | `<repo>/logs` | `grounding.jsonl` is written here |
| `timeout_s` | `20.0` | longest a call may take before the node answers `success: false` |
| `backend` | `gemini` | `gemini`, `ollama` or `fake` (added, see D-129) |

An empty string selects the library's default for the file parameters. The launch arguments are
`repo_root`, `backend` and `timeout_s`. The repository root is found from the launch file
(symlink install), from `SEMANTIC_ROOM_SEARCH_ROOT`, or from `repo_root:=`.

## Behavior

- Start-up: the config, scene graph, vocabulary, prompts, keyword table and backend are loaded
  once. A missing key or model, or a bad file, is logged and the node exits with code 1.
- A call that raises, times out or returns a malformed result is answered with `success: false`
  and a short error. The node does not crash. After a timeout the library call cannot be
  killed; it finishes in the background, bounded by the backend's own timeout (a warning at
  start-up says when that is longer than `timeout_s`).
- Calls run in a `MultiThreadedExecutor` (4 threads) with a reentrant callback group, and each
  call waits for a worker thread with the timeout; a slow call does not block other calls.

## Not yet verified (nothing here has been built or run)

- That `colcon build` generates the messages and that the `ament_python` package installs
  (`--base-paths ros` is my assumption about how this repository is built).
- Imports in the pixi environment: the Python version, pydantic, and that `<repo>/src` on
  `PYTHONPATH` is enough.
- That `additional_env` PYTHONPATH and the substitution-valued parameters in the launch file work
  with this launch_ros version.
- The node itself under a real executor, and the service call from `ros2 service call`.
- Real latency of the Gemini and Ollama backends through the node.
