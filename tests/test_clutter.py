"""ROS-free tests for random clutter (D-090 to D-092)."""
import importlib.util
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

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
ho = _load("house_objects")
vpm = _load("viewpoints")
rg = _load("room_goals")
cl = _load("clutter")

SEEDS = range(5)
LIDAR_PLANE = 0.2  # m; the Waffle's lidar sits below this height


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(PKG / "layout" / "house_layout.yaml")


@pytest.fixture(scope="module")
def types():
    return ho.load_yaml(PKG / "objects" / "clutter.yaml")


@pytest.fixture(scope="module")
def targets(layout):
    catalog = ho.load_yaml(PKG / "objects" / "catalog.yaml")
    return ho.place_objects(layout, catalog, ho.load_yaml(PKG / "objects" / "scenarios" /
                                                          "demo.yaml"))


@pytest.fixture(scope="module")
def viewpoints(layout):
    return vpm.layout_viewpoints(layout)


@pytest.fixture(scope="module")
def reach(layout):
    return cl.Reachability(layout)


@pytest.fixture(scope="module")
def runs(layout, types, targets, viewpoints, reach):
    """Ten clutter objects (the proposal's maximum) for each seed, with the demo targets."""
    return {s: cl.place_clutter(layout, types, 10, s, targets, viewpoints, reach) for s in SEEDS}


def _stops(layout, viewpoints):
    pts = [tuple(p) for v in viewpoints.values() for p in v]
    return pts + [(x, y) for x, y, _ in rg.room_goals(layout["rooms"]).values()]


# ----------------------------------------------------------------- catalog
def test_clutter_is_taller_than_the_lidar_plane(types):
    for kind, spec in types["types"].items():
        assert ho.height(spec) >= LIDAR_PLANE + 0.1, kind


def test_reachability_uses_the_nav2_robot_radius():
    params = yaml.safe_load((PKG / "config" / "nav2_params.yaml").read_text(encoding="utf-8"))
    for name in ("local_costmap", "global_costmap"):
        assert params[name][name]["ros__parameters"]["robot_radius"] == cl.ROBOT_RADIUS


# ----------------------------------------------------------------- placement
def test_places_the_requested_count(runs):
    for seed, placed in runs.items():
        assert len(placed) == 10, seed


def test_same_seed_same_placement_and_seeds_differ(layout, types, targets, viewpoints, reach,
                                                   runs):
    again = cl.place_clutter(layout, types, 10, 0, targets, viewpoints, reach)
    assert [(o["name"], o["x"], o["y"], o["yaw"]) for o in again] == \
           [(o["name"], o["x"], o["y"], o["yaw"]) for o in runs[0]]
    assert len({tuple((o["x"], o["y"]) for o in p) for p in runs.values()}) == len(runs)


def test_count_zero_and_limits(layout, types, viewpoints, reach):
    assert cl.place_clutter(layout, types, 0, 0, (), viewpoints, reach) == []
    for bad in (-1, cl.MAX_COUNT + 1):
        with pytest.raises(cl.ClutterError, match="count"):
            cl.place_clutter(layout, types, bad, 0, (), viewpoints, reach)


def test_clutter_follows_the_placement_rules(runs, layout, targets, viewpoints):
    t = layout["house"]["wall_thickness"]
    walls = [gen.wall_box(p, t) for p in gen.wall_pieces(layout)]
    walls += [gen.door_panel_box(layout, d) for d in layout["doors"] if gen.is_exterior(d)]
    gaps = [ho.door_gap(layout, d) for d in layout["doors"]]
    stops = _stops(layout, viewpoints)
    start = (layout["robot_start"]["x"], layout["robot_start"]["y"])
    rooms = {r["id"]: r["polygon"] for r in layout["rooms"]}
    for seed, placed in runs.items():
        for i, o in enumerate(placed):
            p, r = (o["x"], o["y"]), o["radius"]
            where = (seed, o["name"])
            assert gen.point_in_polygon(p, rooms[o["room"]]), where
            assert min(ho.dist_to_box(p, b) for b in walls) - r >= cl.WALL_CLEARANCE, where
            assert min(ho.point_segment_distance(p, a, b) for a, b in gaps) - r \
                >= cl.DOOR_CLEARANCE, where
            assert min(math.dist(p, s) for s in stops) - r >= cl.STOP_CLEARANCE, where
            assert math.dist(p, start) - r >= cl.START_CLEARANCE, where
            for q in targets:
                assert math.dist(p, (q["x"], q["y"])) - r - q["radius"] >= cl.TARGET_CLEARANCE
            for q in placed[:i]:
                assert math.dist(p, (q["x"], q["y"])) - r - q["radius"] >= cl.CLUTTER_SPACING


def test_every_viewpoint_and_target_stays_reachable(runs, layout, targets, viewpoints, reach):
    stops = _stops(layout, viewpoints)
    for seed, placed in runs.items():
        assert reach.problems(placed, stops, targets) == [], seed


def test_clutter_rests_on_the_floor_and_is_a_static_model(runs, types):
    for placed in runs.values():
        for o in placed:
            spec = types["types"][o["type"]]
            assert o["z"] == pytest.approx(ho.height(spec) / 2)
            model = ET.fromstring(o["sdf"]).find("model")
            assert model.get("name") == o["name"] and model.find("static").text == "true"
            assert o["name"].startswith(cl.MODEL_PREFIX)
        assert len({o["name"] for o in placed}) == len(placed)


# ----------------------------------------------------------------- reachability check itself
def test_empty_house_is_fully_reachable(reach, layout, targets, viewpoints):
    assert reach.problems([], _stops(layout, viewpoints), targets) == []


def test_blocking_a_doorway_is_detected(reach, layout, viewpoints):
    # A large obstacle in the LR-D doorway cuts D off from the rest of the house.
    plug = {"x": 6.95, "y": 1.5, "radius": 0.6}
    problems = reach.problems([plug], [tuple(p) for p in viewpoints["D"]], [])
    assert problems == [f"stop {list(viewpoints['D'][0])}"]


def test_impossible_request_fails_clearly(layout, viewpoints, reach):
    huge = {"types": {"wall": {"shape": "box", "size": [3.0, 3.0, 1.0], "color": [0, 0, 0]}}}
    with pytest.raises(cl.ClutterError, match="placed only 0 of 1"):
        cl.place_clutter(layout, huge, 1, 0, (), viewpoints, reach)
