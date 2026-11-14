"""Random clutter for a trial: placement, reachability check and SDF (D-090 to D-092).

ROS-free (standard library, PyYAML and the sibling helper modules), so it is tested with plain
pytest. spawn_clutter.launch.py uses place_clutter() to spawn into the running world.

A seed fully determines the placement (proposal: fixed seed list, identical conditions for
every method). Clutter is never written to the map, so Nav2 only sees it through the lidar.
"""
from __future__ import annotations

import math
import random
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_house import (  # noqa: E402
    door_panel_box,
    is_exterior,
    point_in_polygon,
    wall_box,
    wall_pieces,
)
from house_objects import (  # noqa: E402
    check_spec,
    dist_to_box,
    door_gap,
    footprint_radius,
    height,
    object_sdf,
    point_segment_distance,
)
from room_goals import room_goals  # noqa: E402
from viewpoints import layout_viewpoints  # noqa: E402

MAX_COUNT = 10           # proposal: 0-10 clutter objects per trial
ATTEMPTS_PER_OBJECT = 1000

# Placement rules (D-091), in meters, from the clutter footprint circle.
WALL_CLEARANCE = 0.15    # not flush against walls (keeps the lidar view of walls clean)
DOOR_CLEARANCE = 0.5     # proposal: at least 0.5 m from doorways
STOP_CLEARANCE = 0.5     # from viewpoints and room tour goals, where the robot stops and turns
START_CLEARANCE = 0.8    # from the robot start pose
TARGET_CLEARANCE = 0.6   # from target objects (they stay visible and approachable)
CLUTTER_SPACING = 0.3    # between clutter objects

# Reachability check (D-091).
ROBOT_RADIUS = 0.22      # same as robot_radius in config/nav2_params.yaml (tested)
REACH_MARGIN = 0.03      # extra clearance for the coarse grid
REACH_GRID = 0.1         # m per cell
STANDOFF = 0.7           # a target counts as approachable from a free cell this close

MODEL_PREFIX = "clutter_"


class ClutterError(ValueError):
    """Clutter cannot be placed as requested."""


def model_name(kind, k):
    return f"{MODEL_PREFIX}{kind}_{k}"


# ---------------------------------------------------------------- reachability
class Reachability:
    """Cells of a REACH_GRID grid where the robot center fits, and a flood fill from the start."""

    def __init__(self, layout, radius=ROBOT_RADIUS + REACH_MARGIN, grid=REACH_GRID):
        W, H = layout["house"]["size"]
        t = layout["house"]["wall_thickness"]
        boxes = [wall_box(p, t) for p in wall_pieces(layout)]
        boxes += [door_panel_box(layout, d) for d in layout["doors"] if is_exterior(d)]
        self.grid, self.radius = grid, radius
        self.nx, self.ny = round(W / grid), round(H / grid)
        self.wall_free = {
            (i, j) for i in range(self.nx) for j in range(self.ny)
            if min(dist_to_box(self.center((i, j)), b) for b in boxes) > radius}
        self.start = self.cell((layout["robot_start"]["x"], layout["robot_start"]["y"]))

    def center(self, cell):
        return ((cell[0] + 0.5) * self.grid, (cell[1] + 0.5) * self.grid)

    def cell(self, p):
        return (math.floor(p[0] / self.grid), math.floor(p[1] / self.grid))

    def near(self, x, y, r):
        """Cells whose center is within r of (x, y)."""
        ci, cj = self.cell((x, y))
        k = math.ceil(r / self.grid) + 1
        return [(i, j) for i in range(ci - k, ci + k + 1) for j in range(cj - k, cj + k + 1)
                if math.hypot((i + 0.5) * self.grid - x, (j + 0.5) * self.grid - y) <= r]

    def reached(self, clutter):
        """Cells the robot center can reach from the start with `clutter` (dicts with x, y,
        radius) in the house."""
        blocked = set()
        for o in clutter:
            blocked.update(self.near(o["x"], o["y"], o["radius"] + self.radius))
        free = self.wall_free - blocked
        if self.start not in free:
            return set()
        seen, todo = {self.start}, deque([self.start])
        while todo:
            i, j = todo.popleft()
            for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if n in free and n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen

    def problems(self, clutter, stops, targets):
        """Descriptions of stops (viewpoints) and targets the robot can no longer reach."""
        seen = self.reached(clutter)
        out = [f"stop {list(s)}" for s in stops if self.cell(s) not in seen]
        for o in targets:
            if not any(c in seen for c in self.near(o["x"], o["y"], STANDOFF)):
                out.append(f"target {o['name']}")
        return out


# ---------------------------------------------------------------- placement
def place_clutter(layout, catalog, count, seed, targets=(), viewpoints=None, reach=None):
    """Place `count` random clutter objects, deterministically for a given seed.

    targets: placed target objects (house_objects.place_objects output) to keep clear of.
    viewpoints: {room: [[x, y], ...]}; computed from the layout if None (takes a few seconds).
    Returns dicts like house_objects.place_objects: name, type, room, x, y, z, yaw, radius, sdf.
    """
    if not 0 <= count <= MAX_COUNT:
        raise ClutterError(f"count must be 0..{MAX_COUNT}, got {count}")
    types = catalog["types"]
    for kind, spec in types.items():
        check_spec(kind, spec)
    kinds = sorted(types)

    W, H = layout["house"]["size"]
    t = layout["house"]["wall_thickness"]
    rooms = layout["rooms"]
    obstacles = [wall_box(p, t) for p in wall_pieces(layout)]
    obstacles += [door_panel_box(layout, d) for d in layout["doors"] if is_exterior(d)]
    gaps = [door_gap(layout, d) for d in layout["doors"]]
    if viewpoints is None:
        viewpoints = layout_viewpoints(layout)
    stops = [tuple(p) for pts in viewpoints.values() for p in pts]
    stops += [(x, y) for x, y, _ in room_goals(rooms).values()]
    start = (layout["robot_start"]["x"], layout["robot_start"]["y"])
    reach = reach or Reachability(layout)
    targets = list(targets)

    rng = random.Random(seed)
    placed, counts = [], {}
    for n in range(count):
        for _ in range(ATTEMPTS_PER_OBJECT):
            kind = rng.choice(kinds)
            x, y = round(rng.uniform(0.0, W), 3), round(rng.uniform(0.0, H), 3)
            yaw = round(rng.uniform(0.0, 2 * math.pi), 3)
            spec = types[kind]
            r = footprint_radius(spec)
            p = (x, y)
            room = next((rm["id"] for rm in rooms if point_in_polygon(p, rm["polygon"])), None)
            if room is None:
                continue
            if (min(dist_to_box(p, b) for b in obstacles) - r < WALL_CLEARANCE
                    or min(point_segment_distance(p, a, b) for a, b in gaps) - r < DOOR_CLEARANCE
                    or min(math.dist(p, s) for s in stops) - r < STOP_CLEARANCE
                    or math.dist(p, start) - r < START_CLEARANCE
                    or any(math.dist(p, (o["x"], o["y"])) - r - o["radius"] < TARGET_CLEARANCE
                           for o in targets)
                    or any(math.dist(p, (o["x"], o["y"])) - r - o["radius"] < CLUTTER_SPACING
                           for o in placed)):
                continue
            candidate = {"x": x, "y": y, "radius": r}
            if reach.problems(placed + [candidate], stops, targets):
                continue
            k = counts.get(kind, 0)
            counts[kind] = k + 1
            name = model_name(kind, k)
            placed.append({"name": name, "type": kind, "room": room, "x": x, "y": y,
                           "z": round(height(spec) / 2, 4), "yaw": yaw, "radius": r,
                           "sdf": object_sdf(name, spec)})
            break
        else:
            raise ClutterError(f"placed only {n} of {count} clutter objects (seed {seed})")
    return placed
