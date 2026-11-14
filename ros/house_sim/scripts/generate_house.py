#!/usr/bin/env python3
"""Generate the Gazebo world, the Nav2 map and the scene graph from layout/house_layout.yaml.

ROS-free: needs only the Python standard library and PyYAML (Pillow only for --preview).
Tests import this file by path (tests/test_house_sim.py), so keep it free of ROS imports.

Usage (from the repository root):
    python3 ros/house_sim/scripts/generate_house.py
    python3 ros/house_sim/scripts/generate_house.py --preview

Outputs
  <pkg>/worlds/house.sdf              Gazebo Harmonic world (walls, closed exterior door, floors)
  <pkg>/maps/house_map.pgm, .yaml     occupancy map for nav2 map_server (same geometry)
  <repo>/data/scene_graph.json        scene graph for lang_grounding ("Interface specs")
  <pkg>/maps/house_map_preview.png    only with --preview (needs Pillow)

Frames (D-050): world frame == Nav2 map frame, origin at the bottom-left outer corner of the
house, x right, y up, meters. Map yaml origin = [-margin, -margin, 0].
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]      # ros/house_sim
REPO = PKG.parents[1]                          # repository root
OUTSIDE = "outside"
EPS = 1e-6
DECIMALS = 4                                   # rounding of computed area / centroid

# Pixel values in the PGM (trinary mode, negate 0).
FREE, OCCUPIED, UNKNOWN = 254, 0, 205

PKG_OUTPUTS = ("worlds/house.sdf", "maps/house_map.pgm", "maps/house_map.yaml")
DATA_OUTPUTS = ("scene_graph.json",)


class LayoutError(ValueError):
    """The layout file is inconsistent (door not on a wall, bad polygon, ...)."""


# ---------------------------------------------------------------- polygon geometry
def edges(poly):
    n = len(poly)
    return [(poly[i], poly[(i + 1) % n]) for i in range(n)]


def signed_area(poly):
    """Shoelace area; positive for counter-clockwise polygons."""
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(poly))


def centroid(poly):
    """Area centroid of a simple polygon (valid for non-convex shapes)."""
    a6 = 6.0 * signed_area(poly)
    cx = cy = 0.0
    for (x0, y0), (x1, y1) in edges(poly):
        w = x0 * y1 - x1 * y0
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    return cx / a6, cy / a6


def point_in_polygon(p, poly):
    """Even-odd test. Points exactly on the boundary may go either way."""
    x, y = p
    inside = False
    for (x0, y0), (x1, y1) in edges(poly):
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def polygon_rects(poly):
    """Split a rectilinear polygon into rectangles [xmin, ymin, xmax, ymax] (D-051).

    Cuts the polygon into vertical strips at every vertex x. Inside one strip, the horizontal
    edges that cross the strip alternate between entering and leaving the polygon, so pairing
    them in y order gives the covered intervals.
    """
    xs = sorted({x for x, _ in poly})
    rects = []
    for xa, xb in zip(xs, xs[1:]):
        xm = (xa + xb) / 2
        ys = sorted(a[1] for a, b in edges(poly)
                    if abs(a[1] - b[1]) < EPS and min(a[0], b[0]) < xm < max(a[0], b[0]))
        for y_lo, y_hi in zip(ys[0::2], ys[1::2]):
            rects.append([xa, y_lo, xb, y_hi])
    return rects


# ---------------------------------------------------------------- walls and doors
def outer_walls(w, h):
    return [[[0.0, 0.0], [w, 0.0]], [[w, 0.0], [w, h]], [[w, h], [0.0, h]], [[0.0, h], [0.0, 0.0]]]


def wall_segments(L):
    """All wall center-line segments (outer walls first), before door gaps are cut."""
    W, H = L["house"]["size"]
    return outer_walls(float(W), float(H)) + [
        [[float(x), float(y)] for x, y in seg] for seg in L["interior_walls"]]


def _wall_axis(seg):
    """(horizontal, fixed coordinate, lo, hi) of an axis-aligned segment."""
    (x1, y1), (x2, y2) = seg
    horizontal = abs(y1 - y2) < EPS
    if not horizontal and abs(x1 - x2) > EPS:
        raise LayoutError(f"wall {seg} is not axis-aligned")
    fixed = y1 if horizontal else x1
    lo, hi = sorted([x1, x2] if horizontal else [y1, y2])
    return horizontal, fixed, lo, hi


def door_on_segment(door, seg):
    """True if the door center is on the segment's line and its full width fits on it."""
    horizontal, fixed, lo, hi = _wall_axis(seg)
    cx, cy = door["center"]
    across, along = (cy, cx) if horizontal else (cx, cy)
    half = door["width"] / 2
    return abs(across - fixed) < EPS and lo - EPS <= along - half and along + half <= hi + EPS


def wall_pieces(L):
    """Solid wall pieces (center-line segments) after cutting every door gap."""
    pieces = []
    for seg in wall_segments(L):
        horizontal, fixed, lo, hi = _wall_axis(seg)
        gaps = []
        for d in L["doors"]:
            if door_on_segment(d, seg):
                along = d["center"][0] if horizontal else d["center"][1]
                gaps.append((along - d["width"] / 2, along + d["width"] / 2))
        cur = lo
        for g0, g1 in sorted(gaps):
            if g0 > cur + EPS:
                pieces.append((cur, g0, horizontal, fixed))
            cur = max(cur, g1)
        if hi > cur + EPS:
            pieces.append((cur, hi, horizontal, fixed))
    return [[[a, f], [b, f]] if hz else [[f, a], [f, b]] for a, b, hz, f in pieces]


def wall_box(piece, t):
    """Center (x, y) and size (sx, sy) of a wall piece, extended by t/2 at both ends."""
    (x1, y1), (x2, y2) = piece
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if abs(y1 - y2) < EPS:
        return cx, cy, abs(x2 - x1) + t, t
    return cx, cy, t, abs(y2 - y1) + t


def door_id(door):
    """d_<A>_<B> in `connects` order; the outside is written "out" (spec example d_E_out)."""
    a, b = ("out" if name == OUTSIDE else name for name in door["connects"])
    return f"d_{a}_{b}"


def is_exterior(door):
    return OUTSIDE in door["connects"]


def door_panel_box(L, door):
    """Center and size of the closed panel filling an exterior door gap (D-052).

    Wall pieces next to the gap reach t/2 into it, so the panel spans the clear opening
    (width - t) and has the wall thickness.
    """
    t = L["house"]["wall_thickness"]
    seg = next(s for s in wall_segments(L) if door_on_segment(door, s))
    horizontal = _wall_axis(seg)[0]
    cx, cy = door["center"]
    length = door["width"] - t
    return (cx, cy, length, t) if horizontal else (cx, cy, t, length)


# ---------------------------------------------------------------- layout loading and checks
def load_layout(path):
    with open(path, encoding="utf-8") as f:
        L = yaml.safe_load(f)
    check_layout(L)
    return L


def check_layout(L):
    t = L["house"]["wall_thickness"]
    room_ids = []
    for r in L["rooms"]:
        rid, poly = r["id"], r["polygon"]
        if rid == OUTSIDE or rid in room_ids:
            raise LayoutError(f"room ID '{rid}' is reserved or duplicated")
        room_ids.append(rid)
        if len(poly) < 4:
            raise LayoutError(f"room {rid}: a rectilinear polygon needs at least 4 vertices")
        for a, b in edges(poly):
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if (dx > EPS) == (dy > EPS):
                raise LayoutError(f"room {rid}: edge {a}->{b} is not axis-aligned or has length 0")
        area = signed_area(poly)
        if area <= EPS:
            raise LayoutError(f"room {rid}: polygon must be counter-clockwise")
        rect_area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in polygon_rects(poly))
        if abs(rect_area - area) > EPS:
            raise LayoutError(f"room {rid}: polygon is not simple (strip area {rect_area} != {area})")

    segments = wall_segments(L)
    for seg in segments:
        _wall_axis(seg)
    ids = []
    for d in L["doors"]:
        a, b = d["connects"]
        did = door_id(d)
        if a == b:
            raise LayoutError(f"door {did}: must connect two different places")
        for name in (a, b):
            if name != OUTSIDE and name not in room_ids:
                raise LayoutError(f"door {did}: unknown room '{name}'")
        if did in ids:
            raise LayoutError(f"duplicate door ID '{did}'")
        ids.append(did)
        if not any(door_on_segment(d, s) for s in segments):
            raise LayoutError(f"door {did}: not fully on any wall center-line segment")
        if is_exterior(d) and d["width"] <= t:
            raise LayoutError(f"door {did}: width must exceed the wall thickness")

    s = L["robot_start"]
    if not any(point_in_polygon((s["x"], s["y"]), r["polygon"]) for r in L["rooms"]):
        raise LayoutError("robot_start is not inside any room")


# ---------------------------------------------------------------- scene graph
_PAIR = re.compile(r"\[\s*([^\[\]\s,]+),\s*([^\[\]\s,]+)\s*\]")


def scene_graph(L):
    """Scene graph dict in the "Interface specs" format (schema_version 1)."""
    rooms = []
    for r in L["rooms"]:
        poly = [[float(x), float(y)] for x, y in r["polygon"]]
        cx, cy = centroid(poly)
        rooms.append({
            "id": r["id"],
            "name": r["name"],
            "polygon": poly,
            "centroid": [round(cx, DECIMALS), round(cy, DECIMALS)],
            "area": round(signed_area(poly), DECIMALS),
        })
    doors = [{"id": door_id(d), "between": list(d["connects"]),
              "position": [float(c) for c in d["center"]]} for d in L["doors"]]
    return {"schema_version": 1, "frame": "map", "units": "m", "rooms": rooms, "doors": doors}


def dump_scene_graph(sg):
    """2-space indented JSON with each [x, y] pair (and each 'between' pair) on one line."""
    return _PAIR.sub(r"[\1, \2]", json.dumps(sg, indent=2)) + "\n"


# ---------------------------------------------------------------- SDF
def sdf_world(L):
    t, h = L["house"]["wall_thickness"], L["house"]["wall_height"]
    W, H = L["house"]["size"]
    links = []
    for i, p in enumerate(wall_pieces(L)):
        cx, cy, sx, sy = wall_box(p, t)
        links.append(f"""
      <link name="wall_{i}">
        <pose>{cx:.3f} {cy:.3f} {h/2:.3f} 0 0 0</pose>
        <collision name="collision"><geometry><box><size>{sx:.3f} {sy:.3f} {h:.3f}</size></box></geometry></collision>
        <visual name="visual">
          <geometry><box><size>{sx:.3f} {sy:.3f} {h:.3f}</size></box></geometry>
          <material><ambient>0.85 0.85 0.82 1</ambient><diffuse>0.85 0.85 0.82 1</diffuse></material>
        </visual>
      </link>""")
    panels = []
    for d in L["doors"]:
        if not is_exterior(d):
            continue
        cx, cy, sx, sy = door_panel_box(L, d)
        panels.append(f"""
      <link name="door_{door_id(d)}">
        <pose>{cx:.3f} {cy:.3f} {h/2:.3f} 0 0 0</pose>
        <collision name="collision"><geometry><box><size>{sx:.3f} {sy:.3f} {h:.3f}</size></box></geometry></collision>
        <visual name="visual">
          <geometry><box><size>{sx:.3f} {sy:.3f} {h:.3f}</size></box></geometry>
          <material><ambient>0.45 0.28 0.15 1</ambient><diffuse>0.45 0.28 0.15 1</diffuse></material>
        </visual>
      </link>""")
    floors = []
    for room in L["rooms"]:
        r, g, b = room["color"]
        for j, (x0, y0, x1, y1) in enumerate(polygon_rects(room["polygon"])):
            floors.append(f"""
      <link name="floor_{room['id']}_{j}">
        <pose>{(x0+x1)/2:.3f} {(y0+y1)/2:.3f} 0.002 0 0 0</pose>
        <visual name="visual">
          <geometry><box><size>{x1-x0:.3f} {y1-y0:.3f} 0.002</size></box></geometry>
          <material><ambient>{r} {g} {b} 1</ambient><diffuse>{r} {g} {b} 1</diffuse></material>
        </visual>
      </link>""")
    return f"""<?xml version="1.0"?>
<!-- AUTO-GENERATED by scripts/generate_house.py from layout/house_layout.yaml. Do not edit by hand. -->
<sdf version="1.8">
  <world name="house">
    <physics type="ode">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1</real_time_factor>
      <real_time_update_rate>1000</real_time_update_rate>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>

    <scene>
      <ambient>0.6 0.6 0.6 1</ambient>
      <background>0.75 0.8 0.85 1</background>
      <shadows>false</shadows>
    </scene>

    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows>
      <pose>{W/2:.1f} {H/2:.1f} 10 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.3 0.2 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry><plane><normal>0 0 1</normal><size>50 50</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>50 50</size></plane></geometry>
          <material><ambient>0.6 0.6 0.6 1</ambient><diffuse>0.6 0.6 0.6 1</diffuse></material>
        </visual>
      </link>
    </model>

    <model name="house_floors">
      <static>true</static>{''.join(floors)}
    </model>

    <model name="house_walls">
      <static>true</static>{''.join(links)}
    </model>

    <model name="house_doors">
      <static>true</static>{''.join(panels)}
    </model>
  </world>
</sdf>
"""


# ---------------------------------------------------------------- map
def map_size(L):
    res, m = L["map"]["resolution"], L["map"]["margin"]
    W, H = L["house"]["size"]
    return int(round((W + 2 * m) / res)), int(round((H + 2 * m) / res))


def map_image(L):
    """Rows of pixel values, row 0 = top of the image (max y), as in the PGM file."""
    res, m = L["map"]["resolution"], L["map"]["margin"]
    W, H = L["house"]["size"]
    t = L["house"]["wall_thickness"]
    nx, ny = map_size(L)
    img = [[UNKNOWN] * nx for _ in range(ny)]

    def fill(x0, y0, x1, y1, val):
        c0, c1 = int((x0 + m) / res), int(round((x1 + m) / res))
        r0, r1 = int((y0 + m) / res), int(round((y1 + m) / res))
        for r in range(max(r0, 0), min(r1, ny)):
            row = img[ny - 1 - r]
            for c in range(max(c0, 0), min(c1, nx)):
                row[c] = val

    def fill_box(cx, cy, sx, sy, val):
        fill(cx - sx / 2, cy - sy / 2, cx + sx / 2, cy + sy / 2, val)

    fill(0, 0, W, H, FREE)
    for p in wall_pieces(L):
        fill_box(*wall_box(p, t), OCCUPIED)
    for d in L["doors"]:
        if is_exterior(d):
            fill_box(*door_panel_box(L, d), OCCUPIED)
    return img


def map_pgm(L):
    nx, ny = map_size(L)
    header = f"P5\n# house_sim generated map\n{nx} {ny}\n255\n".encode()
    return header + bytes(v for row in map_image(L) for v in row)


def map_yaml(L):
    res, m = L["map"]["resolution"], L["map"]["margin"]
    return yaml.safe_dump({
        "image": "house_map.pgm", "mode": "trinary", "resolution": res,
        "origin": [-m, -m, 0.0], "negate": 0,
        "occupied_thresh": 0.65, "free_thresh": 0.25,
    }, sort_keys=False)


def write_preview(L, path):
    from PIL import Image, ImageDraw
    res, m = L["map"]["resolution"], L["map"]["margin"]
    nx, ny = map_size(L)
    im = Image.frombytes("L", (nx, ny), bytes(v for row in map_image(L) for v in row))
    im = im.convert("RGB").resize((nx * 3, ny * 3), Image.NEAREST)
    draw = ImageDraw.Draw(im)

    def to_px(x, y):
        return (x + m) / res * 3, (ny - (y + m) / res) * 3

    for room in L["rooms"]:
        draw.text(to_px(*centroid(room["polygon"])), room["id"], fill=(200, 0, 0))
    s = L["robot_start"]
    px, py = to_px(s["x"], s["y"])
    draw.ellipse([px - 6, py - 6, px + 6, py + 6], outline=(0, 140, 200), width=2)
    im.save(path)


# ---------------------------------------------------------------- outputs
def build_outputs(L):
    """{"pkg": {relative path: bytes}, "data": {relative path: bytes}}. Text uses LF only."""
    return {
        "pkg": {
            "worlds/house.sdf": sdf_world(L).encode(),
            "maps/house_map.pgm": map_pgm(L),
            "maps/house_map.yaml": map_yaml(L).encode(),
        },
        "data": {
            "scene_graph.json": dump_scene_graph(scene_graph(L)).encode(),
        },
    }


def write_outputs(L, pkg_dir, data_dir):
    written = []
    outputs = build_outputs(L)
    for root, files in ((Path(pkg_dir), outputs["pkg"]), (Path(data_dir), outputs["data"])):
        for rel, content in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            written.append(path)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layout", default=str(PKG / "layout" / "house_layout.yaml"))
    ap.add_argument("--pkg-dir", default=str(PKG), help="where worlds/ and maps/ are written")
    ap.add_argument("--data-dir", default=str(REPO / "data"),
                    help="where scene_graph.json is written")
    ap.add_argument("--preview", action="store_true", help="also write maps/house_map_preview.png")
    args = ap.parse_args(argv)

    try:
        L = load_layout(args.layout)
    except LayoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"ERROR: data directory {data_dir} does not exist; pass --data-dir", file=sys.stderr)
        return 1

    written = write_outputs(L, args.pkg_dir, data_dir)
    if args.preview:
        write_preview(L, Path(args.pkg_dir) / "maps" / "house_map_preview.png")
    print(f"{len(wall_pieces(L))} wall pieces, {len(L['doors'])} doors, {len(L['rooms'])} rooms")
    for p in written:
        print(f"  wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
