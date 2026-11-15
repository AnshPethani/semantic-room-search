"""Tests for the house_sim generator and its committed outputs (Phase 3, D-050 to D-057).

Plain pytest, no ROS: the generator is ROS-free and is loaded by file path (D-056).
The committed outputs must be regenerated after any layout change, or the drift test fails.
"""
import copy
import importlib.util
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from lang_grounding.scene_graph import load_scene_graph

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "ros" / "house_sim"
GENERATOR = PKG / "scripts" / "generate_house.py"
LAYOUT = PKG / "layout" / "house_layout.yaml"
SCENE_GRAPH = REPO / "data" / "scene_graph.json"
WORLD = PKG / "worlds" / "house.sdf"
MAP_PGM = PKG / "maps" / "house_map.pgm"
MAP_YAML = PKG / "maps" / "house_map.yaml"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_house", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load_generator()

D001_NAMES = {"E": "entry hall", "K": "kitchen", "LR": "living room", "D": "dining area",
              "B1": "bedroom 1", "B2": "bedroom 2"}
D002 = {"E": {"K", "LR"}, "K": {"E", "LR"}, "B1": {"LR"}, "B2": {"LR"}, "D": {"LR"},
        "LR": {"E", "K", "B1", "B2", "D"}}
GRID = 0.05  # all room vertices lie on this grid, so cell-center sampling is exact


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(LAYOUT)


@pytest.fixture(scope="module")
def graph():
    return load_scene_graph(SCENE_GRAPH)


# ----------------------------------------------------------------- helpers
def _point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _segment_holding_door(layout, door):
    """Independent of the generator: the wall segment that contains the whole door span."""
    half = door["width"] / 2
    for a, b in gen.wall_segments(layout):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        cx, cy = door["center"]
        ends = [(cx - ux * half, cy - uy * half), (cx + ux * half, cy + uy * half)]
        if all(_point_segment_distance(p, a, b) < 1e-6 for p in [(cx, cy), *ends]):
            return (a, b), (ux, uy)
    return None, None


def _dist_to_box(p, box):
    cx, cy, sx, sy = box
    dx = max(abs(p[0] - cx) - sx / 2, 0.0)
    dy = max(abs(p[1] - cy) - sy / 2, 0.0)
    return math.hypot(dx, dy)


def _grid_points(x0, y0, x1, y1):
    """Cell centers of the GRID inside the box; never on a room boundary."""
    nx, ny = round((x1 - x0) / GRID), round((y1 - y0) / GRID)
    for i in range(nx):
        for j in range(ny):
            yield x0 + (i + 0.5) * GRID, y0 + (j + 0.5) * GRID


def _read_pgm(path):
    data = path.read_bytes()
    tokens, i = [], 0
    while len(tokens) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        tokens.append(data[i:j])
        i = j
    i += 1  # exactly one whitespace byte after maxval
    magic, w, h, maxval = tokens
    assert magic == b"P5" and maxval == b"255"
    w, h = int(w), int(h)
    pixels = data[i:]
    assert len(pixels) == w * h
    return w, h, pixels


class _Map:
    def __init__(self):
        meta = yaml.safe_load(MAP_YAML.read_text())
        self.meta = meta
        self.res = meta["resolution"]
        self.ox, self.oy = meta["origin"][:2]
        self.w, self.h, self.pixels = _read_pgm(MAP_PGM)

    def at(self, x, y):
        c = math.floor((x - self.ox) / self.res)
        r = math.floor((y - self.oy) / self.res)  # rows counted from the bottom
        assert 0 <= c < self.w and 0 <= r < self.h, (x, y)
        return self.pixels[(self.h - 1 - r) * self.w + c]

    def cell_center(self, c, r):
        return self.ox + (c + 0.5) * self.res, self.oy + (r + 0.5) * self.res


@pytest.fixture(scope="module")
def occ_map():
    return _Map()


# ----------------------------------------------------------------- scene graph
def test_scene_graph_loads_with_loader(graph):
    assert graph.frame == "map" and graph.units == "m" and graph.schema_version == 1
    assert graph.room_ids == ["E", "K", "LR", "D", "B1", "B2"]
    assert {r.id: r.name for r in graph.rooms} == D001_NAMES


def test_neighbors_equal_d002_exactly(graph):
    neighbors = graph.neighbors
    assert {k: set(v) for k, v in neighbors.items()} == D002
    assert all(len(v) == len(set(v)) for v in neighbors.values())
    assert graph.exterior_rooms == ("E",)


def test_door_ids(graph):
    assert sorted(d.id for d in graph.doors) == sorted(
        ["d_E_LR", "d_E_K", "d_K_LR", "d_LR_D", "d_LR_B1", "d_LR_B2", "d_E_out"])
    for d in graph.doors:
        a, b = ("out" if n == "outside" else n for n in d.between)
        assert d.id == f"d_{a}_{b}"
    assert next(d for d in graph.doors if d.id == "d_E_out").between == ["E", "outside"]


def test_lr_is_six_vertex_l_shape(graph):
    poly = graph.room("LR").polygon
    assert len(poly) == 6
    assert gen.signed_area([list(p) for p in poly]) > 0  # counter-clockwise


def test_scene_graph_matches_layout(layout, graph):
    for r in layout["rooms"]:
        room = graph.room(r["id"])
        assert [list(p) for p in room.polygon] == r["polygon"]
        cx, cy = gen.centroid(r["polygon"])
        assert room.area == pytest.approx(gen.signed_area(r["polygon"]), abs=1e-4)
        assert room.centroid == pytest.approx((cx, cy), abs=1e-4)
    positions = {d.id: list(d.position) for d in graph.doors}
    assert positions == {gen.door_id(d): d["center"] for d in layout["doors"]}


def test_room_areas_sum_to_house_footprint(graph):
    assert sum(r.area for r in graph.rooms) == pytest.approx(12.0 * 9.0, abs=0.05)


def test_room_polygons_do_not_overlap_and_cover_the_house(layout):
    polys = {r["id"]: r["polygon"] for r in layout["rooms"]}
    for poly in polys.values():
        for v in (c for p in poly for c in p):
            assert abs(v / GRID - round(v / GRID)) < 1e-6, "vertex not on the sampling grid"
    W, H = layout["house"]["size"]
    for p in _grid_points(0.0, 0.0, W, H):
        owners = [rid for rid, poly in polys.items() if gen.point_in_polygon(p, poly)]
        assert len(owners) == 1, f"point {p} is in rooms {owners}"


def test_floor_rects_cover_each_polygon_exactly(layout):
    for r in layout["rooms"]:
        poly = r["polygon"]
        rects = gen.polygon_rects(poly)
        area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
        assert area == pytest.approx(gen.signed_area(poly), abs=1e-9), r["id"]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        for p in _grid_points(min(xs), min(ys), max(xs), max(ys)):
            n = sum(x0 < p[0] < x1 and y0 < p[1] < y1 for x0, y0, x1, y1 in rects)
            assert n == (1 if gen.point_in_polygon(p, poly) else 0), (r["id"], p)


def test_lr_floor_is_two_rects(layout):
    lr = next(r for r in layout["rooms"] if r["id"] == "LR")
    assert sorted(gen.polygon_rects(lr["polygon"])) == [[3.3, 4.1, 5.1, 6.1],
                                                        [5.1, 1.5, 8.8, 6.1]]


# ----------------------------------------------------------------- layout geometry
def test_every_door_lies_on_a_wall_center_line_segment(layout):
    for d in layout["doors"]:
        seg, _ = _segment_holding_door(layout, d)
        assert seg is not None, f"door {gen.door_id(d)} is not on a wall center-line segment"


def test_start_pose_in_e_and_clear_of_walls(layout, graph):
    s = layout["robot_start"]
    p = (s["x"], s["y"])
    inside = [r.id for r in graph.rooms if gen.point_in_polygon(p, [list(v) for v in r.polygon])]
    assert inside == ["E"]
    t = layout["house"]["wall_thickness"]
    boxes = [gen.wall_box(piece, t) for piece in gen.wall_pieces(layout)]
    boxes += [gen.door_panel_box(layout, d) for d in layout["doors"] if gen.is_exterior(d)]
    assert min(_dist_to_box(p, b) for b in boxes) >= 0.4


# ----------------------------------------------------------------- map
def test_map_yaml_matches_layout(layout, occ_map):
    res, m = layout["map"]["resolution"], layout["map"]["margin"]
    W, H = layout["house"]["size"]
    assert occ_map.meta["image"] == "house_map.pgm"
    assert occ_map.meta["mode"] == "trinary"
    assert occ_map.res == res
    assert occ_map.meta["origin"] == [-m, -m, 0.0]
    assert (occ_map.w, occ_map.h) == (round((W + 2 * m) / res), round((H + 2 * m) / res))


def test_wall_cells_are_occupied(layout, occ_map):
    step = occ_map.res / 2
    for (x1, y1), (x2, y2) in gen.wall_pieces(layout):
        n = max(1, math.ceil(math.hypot(x2 - x1, y2 - y1) / step))
        for k in range(n + 1):
            x, y = x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n
            assert occ_map.at(x, y) == gen.OCCUPIED, (x, y)


def test_door_gap_centers(layout, occ_map):
    t = layout["house"]["wall_thickness"]
    for d in layout["doors"]:
        _, (ux, uy) = _segment_holding_door(layout, d)
        nx, ny = -uy, ux  # across the wall
        cx, cy = d["center"]
        if gen.is_exterior(d):
            # Closed panel: its outer face can rasterize one cell short, so probe near the center.
            across, expected = (-0.02, 0.0, 0.02), gen.OCCUPIED
        else:
            # Open gap: free across the whole wall thickness.
            across, expected = (-(t / 2 - 0.01), 0.0, t / 2 - 0.01), gen.FREE
        values = {occ_map.at(cx + nx * a, cy + ny * a) for a in across}
        assert values == {expected}, gen.door_id(d)


def test_start_pose_is_free(layout, occ_map):
    s = layout["robot_start"]
    assert occ_map.at(s["x"], s["y"]) == gen.FREE


def test_outside_the_house_is_unknown(layout, occ_map):
    W, H = layout["house"]["size"]
    clear = layout["house"]["wall_thickness"] / 2 + 1.5 * occ_map.res  # beyond the outer walls
    checked = 0
    for r in range(occ_map.h):
        for c in range(occ_map.w):
            x, y = occ_map.cell_center(c, r)
            if x < -clear or x > W + clear or y < -clear or y > H + clear:
                assert occ_map.at(x, y) == gen.UNKNOWN, (x, y)
                checked += 1
    assert checked > 0


# ----------------------------------------------------------------- SDF
def _floats(text):
    return [float(v) for v in text.split()]


@pytest.fixture(scope="module")
def world():
    return ET.parse(WORLD).getroot().find("world")


def _model(world, name):
    return next(m for m in world.findall("model") if m.get("name") == name)


def test_sdf_has_one_collision_box_per_wall_piece(layout, world):
    t, h = layout["house"]["wall_thickness"], layout["house"]["wall_height"]
    pieces = gen.wall_pieces(layout)
    links = _model(world, "house_walls").findall("link")
    assert len(links) == len(pieces)
    for link, piece in zip(links, pieces, strict=True):
        collisions = link.findall("collision")
        assert len(collisions) == 1
        size = _floats(collisions[0].find("geometry/box/size").text)
        pose = _floats(link.find("pose").text)
        cx, cy, sx, sy = gen.wall_box(piece, t)
        assert size == pytest.approx([sx, sy, h], abs=1e-3)
        assert pose[:3] == pytest.approx([cx, cy, h / 2], abs=1e-3)


def test_sdf_has_closed_panel_at_exterior_door(layout, world):
    t, h = layout["house"]["wall_thickness"], layout["house"]["wall_height"]
    door = next(d for d in layout["doors"] if gen.door_id(d) == "d_E_out")
    links = _model(world, "house_doors").findall("link")
    assert [link.get("name") for link in links] == ["door_d_E_out"]
    link = links[0]
    pose = _floats(link.find("pose").text)
    assert pose[:2] == pytest.approx(door["center"], abs=1e-3)
    size = _floats(link.find("collision/geometry/box/size").text)
    # The panel spans the clear opening between the wall ends and is as thick as the wall.
    assert sorted(size[:2]) == pytest.approx(sorted([door["width"] - t, t]), abs=1e-3)
    assert size[2] == pytest.approx(h, abs=1e-3)


# ----------------------------------------------------------------- drift and formats
OUTPUTS = ([("pkg", rel) for rel in gen.PKG_OUTPUTS]
           + [("data", rel) for rel in gen.DATA_OUTPUTS])


@pytest.fixture(scope="module")
def generated(layout, tmp_path_factory):
    """Generate once into a temporary directory (viewpoint selection takes a few seconds)."""
    out = tmp_path_factory.mktemp("generated")
    gen.write_outputs(layout, out / "pkg", out / "data")
    return out


@pytest.mark.parametrize("root,rel", OUTPUTS)
def test_committed_outputs_match_generator(generated, root, rel):
    committed = (PKG if root == "pkg" else REPO / "data") / rel
    assert committed.exists(), f"{committed} is missing; run the generator"
    new, old = (generated / root / rel).read_bytes(), committed.read_bytes()
    if committed.suffix != ".pgm":  # tolerate a CRLF checkout of text files (D-057)
        new, old = new.replace(b"\r\n", b"\n"), old.replace(b"\r\n", b"\n")
    assert new == old, f"{committed.relative_to(REPO)} is stale; run the generator"


def test_rooms_yaml_is_gone():
    assert not (PKG / "config" / "rooms.yaml").exists(), "D-055: config/rooms.yaml was removed"


# ----------------------------------------------------------------- generator checks
def test_generator_rejects_door_off_wall(layout):
    bad = copy.deepcopy(layout)
    bad["doors"][0]["center"] = [3.0, 5.1]
    with pytest.raises(gen.LayoutError, match="not fully on any wall"):
        gen.check_layout(bad)


def test_generator_rejects_clockwise_polygon(layout):
    bad = copy.deepcopy(layout)
    bad["rooms"][0]["polygon"].reverse()
    with pytest.raises(gen.LayoutError, match="counter-clockwise"):
        gen.check_layout(bad)
