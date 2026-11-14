"""ROS-free tests for search viewpoints (D-080, D-081)."""
import copy
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from lang_grounding.scene_graph import load_scene_graph

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "ros" / "house_sim"
SCRIPTS = PKG / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate_house")
vp = _load("viewpoints")

# Counts for this house at camera_range 3.0 m: E and D fit in one 3 m circle around their
# center; K, B1, B2 are too long; LR's arm is out of sight or range from any single point.
EXPECTED_COUNTS = {"E": 1, "K": 2, "LR": 2, "D": 1, "B1": 2, "B2": 2}


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(PKG / "layout" / "house_layout.yaml")


@pytest.fixture(scope="module")
def viewpoints(layout):
    return vp.layout_viewpoints(layout)


@pytest.fixture(scope="module")
def rooms(layout):
    return {r["id"]: r["polygon"] for r in layout["rooms"]}


def test_config_follows_the_proposal(layout):
    cfg = layout["viewpoints"]
    assert 1 <= cfg["max_per_room"] <= 3
    assert cfg["camera_range"] > 0 and cfg["wall_clearance"] > 0


def test_viewpoint_counts(viewpoints):
    assert {rid: len(v) for rid, v in viewpoints.items()} == EXPECTED_COUNTS


def test_scene_graph_stores_the_viewpoints(viewpoints):
    graph = load_scene_graph(REPO / "data" / "scene_graph.json")  # loader ignores the field
    raw = json.loads((REPO / "data" / "scene_graph.json").read_text())
    assert [r["id"] for r in raw["rooms"]] == graph.room_ids
    assert {r["id"]: r["viewpoints"] for r in raw["rooms"]} == viewpoints


def test_each_viewpoint_is_inside_its_own_room_only(viewpoints, rooms):
    for rid, points in viewpoints.items():
        for p in points:
            inside = [r for r, poly in rooms.items() if gen.point_in_polygon(p, poly)]
            assert inside == [rid], (rid, p)


def test_viewpoints_leave_room_to_turn(viewpoints, layout):
    t = layout["house"]["wall_thickness"]
    need = layout["viewpoints"]["wall_clearance"]
    boxes = [gen.wall_box(p, t) for p in gen.wall_pieces(layout)]
    boxes += [gen.door_panel_box(layout, d) for d in layout["doors"] if gen.is_exterior(d)]
    for rid, points in viewpoints.items():
        for x, y in points:
            d = min(math.hypot(max(abs(x - cx) - sx / 2, 0), max(abs(y - cy) - sy / 2, 0))
                    for cx, cy, sx, sy in boxes)
            assert d >= need - 1e-9, (rid, x, y, d)


def test_every_floor_point_is_seen(viewpoints, rooms, layout):
    # Independent of the generator's sampling: a finer 0.1 m grid. A point between the
    # generator's 0.2 m samples may lie up to half a cell diagonal farther away.
    cfg = layout["viewpoints"]
    t = layout["house"]["wall_thickness"]
    reach = cfg["camera_range"] + cfg["target_grid"] / math.sqrt(2)
    for rid, poly in rooms.items():
        for q in vp.grid_points(poly, 0.1, t / 2 + vp.TARGET_MARGIN):
            assert any(math.dist(p, q) <= reach and vp.visible(p, q, poly)
                       for p in viewpoints[rid]), (rid, q)


def test_rooms_with_two_viewpoints_cannot_do_with_one(viewpoints, rooms, layout):
    cfg = dict(layout["viewpoints"], max_per_room=1)
    t = layout["house"]["wall_thickness"]
    for rid, points in viewpoints.items():
        if len(points) > 1:
            with pytest.raises(vp.ViewpointError):
                vp.room_viewpoints(rooms[rid], cfg, t)


def test_line_of_sight_in_the_l_shaped_room(rooms):
    lr = rooms["LR"]
    assert not vp.visible((3.5, 4.3), (8.5, 1.7), lr)  # cut by K's corner
    assert vp.visible((4.0, 5.5), (8.0, 5.5), lr)


def test_too_short_camera_range_is_rejected(layout):
    bad = copy.deepcopy(layout)
    bad["viewpoints"]["camera_range"] = 1.0
    bad["viewpoints"]["max_per_room"] = 1
    with pytest.raises(gen.LayoutError, match="viewpoints"):
        gen.scene_graph(bad)


def test_layout_without_viewpoint_config_is_rejected(layout):
    bad = copy.deepcopy(layout)
    del bad["viewpoints"]
    with pytest.raises(gen.LayoutError, match="viewpoints"):
        gen.check_layout(bad)
