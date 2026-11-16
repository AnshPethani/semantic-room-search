"""Scene graph: rooms as nodes, doors as edges (D-003, D-022).

Pure Python (standard library plus pydantic). No ROS imports.

Usage:
    python -m lang_grounding.scene_graph validate data/scene_graph.placeholder.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
OUTSIDE = "outside"

# D-022 tolerances.
AREA_TOL = 0.05
CENTROID_TOL = 0.05
DOOR_TOL = 0.05  # metres
VIEWPOINT_TOL = 0.05  # metres; a viewpoint this close to the boundary still counts as inside
_EPS = 1e-9  # geometric zero for orientation tests


class SceneGraphError(ValueError):
    """Raised when a scene graph file is malformed or breaks a D-022 rule."""


Coord = Annotated[float, Field(allow_inf_nan=False)]
Point = tuple[Coord, Coord]


class Room(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    polygon: list[Point]
    centroid: Point
    area: Coord
    viewpoints: list[Point] | None = None  # optional, from the viewpoint generator (D-047)


class Door(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    between: list[str]
    position: Point


class SceneGraph(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int
    frame: Literal["map"]
    units: Literal["m"]
    rooms: list[Room]
    doors: list[Door]

    @property
    def room_ids(self) -> list[str]:
        return [r.id for r in self.rooms]

    def room(self, room_id: str) -> Room:
        for r in self.rooms:
            if r.id == room_id:
                return r
        raise KeyError(room_id)

    @property
    def neighbors(self) -> dict[str, tuple[str, ...]]:
        """Room ID -> IDs of rooms connected to it by a door (D-002).

        Derived from `doors`; "outside" is excluded. Order follows the room order in the file.
        """
        result: dict[str, list[str]] = {r.id: [] for r in self.rooms}
        for door in self.doors:
            a, b = door.between
            if OUTSIDE in (a, b):
                continue
            if b not in result[a]:
                result[a].append(b)
            if a not in result[b]:
                result[b].append(a)
        order = {rid: i for i, rid in enumerate(self.room_ids)}
        return {rid: tuple(sorted(ns, key=order.__getitem__)) for rid, ns in result.items()}

    @property
    def exterior_rooms(self) -> tuple[str, ...]:
        """IDs of rooms that have a door to the outside."""
        ids = {d.between[0] if d.between[1] == OUTSIDE else d.between[1]
               for d in self.doors if OUTSIDE in d.between}
        return tuple(rid for rid in self.room_ids if rid in ids)


# --------------------------------------------------------------------------- geometry

def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _orient(p: Point, q: Point, r: Point) -> int:
    v = _cross(p, q, r)
    if abs(v) <= _EPS:
        return 0
    return 1 if v > 0 else -1


def _in_box(p: Point, a: Point, b: Point) -> bool:
    return (min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS)


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """True if closed segments p1p2 and p3p4 share any point (touching counts)."""
    o1, o2 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    o3, o4 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and _in_box(p3, p1, p2))
            or (o2 == 0 and _in_box(p4, p1, p2))
            or (o3 == 0 and _in_box(p1, p3, p4))
            or (o4 == 0 and _in_box(p2, p3, p4)))


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _signed_area(poly: list[Point]) -> float:
    n = len(poly)
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)
    )


def _centroid(poly: list[Point]) -> tuple[float, float]:
    """Area centroid of a simple polygon (valid for non-convex shapes)."""
    n = len(poly)
    a6 = 6.0 * _signed_area(poly)
    cx = cy = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        w = x0 * y1 - x1 * y0
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    return cx / a6, cy / a6


def _distance_to_boundary(p: Point, poly: list[Point]) -> float:
    n = len(poly)
    return min(_point_segment_distance(p, poly[i], poly[(i + 1) % n]) for i in range(n))


def _point_in_polygon(p: Point, poly: list[Point]) -> bool:
    """Even-odd ray casting; correct for non-convex simple polygons (boundary not handled)."""
    px, py = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < x_cross:
                inside = not inside
    return inside


# --------------------------------------------------------------------------- validation

def _check_polygon(room: Room) -> None:
    rid, poly = room.id, room.polygon
    n = len(poly)
    if n < 3:
        raise SceneGraphError(
            f"room '{rid}': polygon needs at least 3 vertices, got {n}")

    for i in range(n):
        if poly[i] == poly[(i + 1) % n]:
            raise SceneGraphError(
                f"room '{rid}': polygon has repeated consecutive vertex {list(poly[i])}")

    # Adjacent edges that double back on each other overlap, so the polygon is not simple.
    for i in range(n):
        p, q, r = poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        if _orient(p, q, r) == 0 and ((q[0] - p[0]) * (r[0] - q[0])
                                      + (q[1] - p[1]) * (r[1] - q[1])) < 0:
            raise SceneGraphError(
                f"room '{rid}': polygon self-intersects (edge at vertex {(i + 1) % n} "
                f"doubles back on the previous edge)")

    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges share a vertex by construction
            if _segments_intersect(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                raise SceneGraphError(
                    f"room '{rid}': polygon self-intersects (edge {i} and edge {j} touch or "
                    f"cross)")

    signed = _signed_area(poly)
    if abs(signed) <= _EPS:
        raise SceneGraphError(f"room '{rid}': polygon has zero area")
    if signed < 0:
        raise SceneGraphError(
            f"room '{rid}': polygon vertices are clockwise; they must be counter-clockwise")

    if abs(room.area - signed) > AREA_TOL:
        raise SceneGraphError(
            f"room '{rid}': stored area {room.area} does not match polygon area "
            f"{signed:.4f} (tolerance {AREA_TOL})")
    cx, cy = _centroid(poly)
    if abs(room.centroid[0] - cx) > CENTROID_TOL or abs(room.centroid[1] - cy) > CENTROID_TOL:
        raise SceneGraphError(
            f"room '{rid}': stored centroid {list(room.centroid)} does not match polygon "
            f"centroid [{cx:.4f}, {cy:.4f}] (tolerance {CENTROID_TOL} per coordinate)")


def _check_viewpoints(room: Room) -> None:
    for i, vp in enumerate(room.viewpoints or []):
        if _point_in_polygon(vp, room.polygon):
            continue
        if _distance_to_boundary(vp, room.polygon) <= VIEWPOINT_TOL:
            continue
        raise SceneGraphError(
            f"room '{room.id}': viewpoint {i} {list(vp)} is outside the room polygon "
            f"(boundary tolerance {VIEWPOINT_TOL} m)")


def _check_door(door: Door, rooms: dict[str, Room]) -> None:
    did = door.id
    if len(door.between) != 2:
        raise SceneGraphError(
            f"door '{did}': 'between' must name exactly 2 places, got {len(door.between)}")
    a, b = door.between
    if a == b:
        raise SceneGraphError(f"door '{did}': connects '{a}' to itself; need two different rooms")
    for name in (a, b):
        if name != OUTSIDE and name not in rooms:
            raise SceneGraphError(f"door '{did}': unknown room '{name}' in 'between'")
    for name in (a, b):
        if name == OUTSIDE:
            continue
        dist = _distance_to_boundary(door.position, rooms[name].polygon)
        if dist > DOOR_TOL:
            raise SceneGraphError(
                f"door '{did}': position {list(door.position)} is {dist:.3f} m from the "
                f"boundary of room '{name}' (tolerance {DOOR_TOL} m); it must lie on the "
                f"boundary of each room it connects")


def _validate(graph: SceneGraph) -> None:
    if not graph.rooms:
        raise SceneGraphError("scene graph has no rooms")

    rooms: dict[str, Room] = {}
    for room in graph.rooms:
        if room.id == OUTSIDE:
            raise SceneGraphError(f"room ID '{OUTSIDE}' is reserved and cannot be a room")
        if room.id in rooms:
            raise SceneGraphError(f"duplicate room ID '{room.id}'")
        rooms[room.id] = room

    for room in graph.rooms:
        _check_polygon(room)
        _check_viewpoints(room)
    seen_doors: set[str] = set()
    for door in graph.doors:
        if door.id in seen_doors:
            raise SceneGraphError(f"duplicate door ID '{door.id}'")
        seen_doors.add(door.id)
        _check_door(door, rooms)


def _format_pydantic_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


# --------------------------------------------------------------------------- loading

def parse_scene_graph(data: Any) -> SceneGraph:
    """Validate a decoded JSON object and return a SceneGraph. Raises SceneGraphError."""
    if isinstance(data, dict) and "schema_version" in data \
            and data["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise SceneGraphError(
            f"unsupported schema_version {data['schema_version']!r}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    try:
        graph = SceneGraph.model_validate(data)
    except ValidationError as exc:
        raise SceneGraphError(f"invalid scene graph structure: {_format_pydantic_errors(exc)}") \
            from exc
    _validate(graph)
    return graph


def load_scene_graph(path: str | Path) -> SceneGraph:
    """Read and validate a scene graph JSON file. Raises SceneGraphError."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SceneGraphError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SceneGraphError(f"{path} is not valid JSON: {exc}") from exc
    return parse_scene_graph(data)


# --------------------------------------------------------------------------- prompt text

def render_for_prompt(graph: SceneGraph) -> str:
    """Compact text description of the building for the LLM. Contains no object information."""
    neighbors = graph.neighbors
    names = {r.id: r.name for r in graph.rooms}
    exterior = set(graph.exterior_rooms)

    lines = [
        "Building layout (areas in square meters).",
        f"The building has {len(graph.rooms)} rooms. "
        'In this description, "next to", "adjacent to", "neighboring" and "beside" all mean '
        '"connected by a door". Two rooms that only share a wall, with no door between them, '
        "are NOT next to each other.",
        "Rooms:",
    ]
    for room in graph.rooms:
        ns = neighbors[room.id]
        connected = ", ".join(f"{n} ({names[n]})" for n in ns) if ns else "none"
        line = (f"- {room.id}: {room.name}, {room.area:.1f} m^2. "
                f"Connected by a door to: {connected}.")
        if room.id in exterior:
            line += " Also has a door to the outside."
        lines.append(line)
    return "\n".join(lines)


def render_names_only(graph: SceneGraph) -> str:
    """Ablation variant of the building description: room IDs and names only (D-124).

    No areas, no doors or adjacency, no exterior-door note, and no definition of "next to":
    the model gets no information about how the rooms are connected.
    """
    lines = [f"The building has {len(graph.rooms)} rooms:"]
    lines.extend(f"- {room.id}: {room.name}" for room in graph.rooms)
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lang_grounding.scene_graph")
    sub = parser.add_subparsers(dest="command", required=True)
    p_validate = sub.add_parser("validate", help="validate a scene graph JSON file")
    p_validate.add_argument("file")
    args = parser.parse_args(argv)

    try:
        graph = load_scene_graph(args.file)
    except SceneGraphError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {args.file} ({len(graph.rooms)} rooms, {len(graph.doors)} doors)")
    for rid, ns in graph.neighbors.items():
        print(f"  {rid}: {', '.join(ns) if ns else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
