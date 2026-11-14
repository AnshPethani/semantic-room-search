"""Target objects: catalog, scenario files, placement checks and SDF (D-070 to D-073).

ROS-free (standard library, PyYAML and the generate_house / room_goals helpers), so the
placement rules are tested with plain pytest. spawn_objects.launch.py uses place_objects()
to spawn the objects into the running Gazebo world.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_house import (  # noqa: E402
    door_on_segment,
    door_panel_box,
    is_exterior,
    point_in_polygon,
    wall_box,
    wall_pieces,
    wall_segments,
)
from room_goals import room_goals  # noqa: E402

# Placement rules (D-072), in meters. Distances are from the object's footprint circle.
WALL_CLEARANCE = 0.3    # to wall surfaces and the closed exterior door panel
DOOR_CLEARANCE = 0.5    # to every door gap (same rule as the proposal's clutter)
GOAL_CLEARANCE = 0.6    # to every room tour goal (room_goals.py)
START_CLEARANCE = 0.8   # to the robot start pose
OBJECT_SPACING = 0.3    # between objects

MODEL_PREFIX = "obj_"


class ObjectError(ValueError):
    """A catalog or scenario entry is invalid or breaks a placement rule."""


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- shapes
def _check_spec(label, spec):
    shape = spec.get("shape")
    needed = {"box": ("size",), "cylinder": ("radius", "length"), "sphere": ("radius",)}
    if shape not in needed:
        raise ObjectError(f"class '{label}': unknown shape {shape!r}")
    for key in needed[shape]:
        if key not in spec:
            raise ObjectError(f"class '{label}': {shape} needs '{key}'")


def footprint_radius(spec):
    if spec["shape"] == "box":
        return math.hypot(spec["size"][0], spec["size"][1]) / 2
    return spec["radius"]


def height(spec):
    return {"box": lambda: spec["size"][2], "cylinder": lambda: spec["length"],
            "sphere": lambda: 2 * spec["radius"]}[spec["shape"]]()


def model_name(label, k):
    """Gazebo model name: obj_<label with spaces as underscores>_<k> (D-073)."""
    return f"{MODEL_PREFIX}{label.replace(' ', '_')}_{k}"


def label_from_model_name(name):
    """Inverse of model_name (COCO names contain spaces but no underscores)."""
    if not name.startswith(MODEL_PREFIX):
        raise ValueError(f"not an object model name: {name}")
    return name[len(MODEL_PREFIX):].rsplit("_", 1)[0].replace("_", " ")


def object_sdf(name, spec):
    if spec["shape"] == "box":
        geom = "<box><size>{:.3f} {:.3f} {:.3f}</size></box>".format(*spec["size"])
    elif spec["shape"] == "cylinder":
        geom = (f"<cylinder><radius>{spec['radius']:.3f}</radius>"
                f"<length>{spec['length']:.3f}</length></cylinder>")
    else:
        geom = f"<sphere><radius>{spec['radius']:.3f}</radius></sphere>"
    r, g, b = spec["color"]
    return f"""<?xml version="1.0"?>
<sdf version="1.8">
  <model name="{name}">
    <static>true</static>
    <link name="link">
      <collision name="collision"><geometry>{geom}</geometry></collision>
      <visual name="visual">
        <geometry>{geom}</geometry>
        <material><ambient>{r} {g} {b} 1</ambient><diffuse>{r} {g} {b} 1</diffuse></material>
      </visual>
    </link>
  </model>
</sdf>
"""


# ---------------------------------------------------------------- placement
def _point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _dist_to_box(p, box):
    cx, cy, sx, sy = box
    return math.hypot(max(abs(p[0] - cx) - sx / 2, 0.0), max(abs(p[1] - cy) - sy / 2, 0.0))


def door_gap(layout, door):
    """End points of a door's gap on its wall center-line."""
    seg = next(s for s in wall_segments(layout) if door_on_segment(door, s))
    cx, cy = door["center"]
    h = door["width"] / 2
    if abs(seg[0][1] - seg[1][1]) < 1e-6:  # horizontal wall
        return (cx - h, cy), (cx + h, cy)
    return (cx, cy - h), (cx, cy + h)


def place_objects(layout, catalog, scenario):
    """Check a scenario against the layout and return one dict per object, in file order:
    name, label, room, x, y, z (half the height, so it rests on the floor), yaw, radius, sdf.
    Raises ObjectError naming the object and the broken rule.
    """
    classes = catalog["classes"]
    for label, spec in classes.items():
        _check_spec(label, spec)
    rooms = {r["id"]: r for r in layout["rooms"]}
    t = layout["house"]["wall_thickness"]
    obstacles = [wall_box(p, t) for p in wall_pieces(layout)]
    obstacles += [door_panel_box(layout, d) for d in layout["doors"] if is_exterior(d)]
    gaps = [door_gap(layout, d) for d in layout["doors"]]
    goals = room_goals(layout["rooms"])
    start = (layout["robot_start"]["x"], layout["robot_start"]["y"])

    placed, counts = [], {}
    for i, obj in enumerate(scenario["objects"]):
        label, room = obj["label"], obj["room"]
        where = f"object {i} ({label} in {room})"
        if label not in classes:
            raise ObjectError(f"{where}: unknown class '{label}'")
        if room not in rooms:
            raise ObjectError(f"{where}: unknown room '{room}'")
        spec = classes[label]
        r = footprint_radius(spec)
        x, y = (float(v) for v in obj["xy"])
        p = (x, y)

        if not point_in_polygon(p, rooms[room]["polygon"]):
            raise ObjectError(f"{where}: {list(p)} is not inside room {room}")
        checks = [
            ("walls", min(_dist_to_box(p, b) for b in obstacles), WALL_CLEARANCE),
            ("door gaps", min(_point_segment_distance(p, a, b) for a, b in gaps), DOOR_CLEARANCE),
            ("room goals", min(math.hypot(x - gx, y - gy) for gx, gy, _ in goals.values()),
             GOAL_CLEARANCE),
            ("robot start", math.hypot(x - start[0], y - start[1]), START_CLEARANCE),
        ]
        for what, dist, need in checks:
            if dist - r < need:
                raise ObjectError(f"{where}: {dist - r:.2f} m from {what}, needs {need} m")
        for q in placed:
            gap = math.hypot(x - q["x"], y - q["y"]) - r - q["radius"]
            if gap < OBJECT_SPACING:
                raise ObjectError(f"{where}: {gap:.2f} m from {q['name']}, needs "
                                  f"{OBJECT_SPACING} m")

        k = counts.get(label, 0)
        counts[label] = k + 1
        name = model_name(label, k)
        placed.append({"name": name, "label": label, "room": room, "x": x, "y": y,
                       "z": round(height(spec) / 2, 4), "yaw": float(obj.get("yaw", 0.0)),
                       "radius": r, "sdf": object_sdf(name, spec)})
    return placed
