"""ROS-free tests for the Nav2 step (D-060 to D-064): room goals and the Nav2 params edits."""
import ast
import importlib.util
import math
import sys
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
rg = _load("room_goals")

MIN_WALL_CLEARANCE = 0.5  # m from the wall surface; robot radius ~0.22 plus margin


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(PKG / "layout" / "house_layout.yaml")


@pytest.fixture(scope="module")
def goals(layout):
    return rg.room_goals(layout["rooms"])


def _dist_to_box(p, box):
    cx, cy, sx, sy = box
    return math.hypot(max(abs(p[0] - cx) - sx / 2, 0.0), max(abs(p[1] - cy) - sy / 2, 0.0))


def test_one_goal_per_room(layout, goals):
    assert list(goals) == [r["id"] for r in layout["rooms"]]


def test_each_goal_is_inside_its_own_room_only(layout, goals):
    for rid, (x, y, _) in goals.items():
        inside = [r["id"] for r in layout["rooms"] if gen.point_in_polygon((x, y), r["polygon"])]
        assert inside == [rid], (rid, x, y)


def test_goals_are_clear_of_walls_and_doors(layout, goals):
    t = layout["house"]["wall_thickness"]
    boxes = [gen.wall_box(p, t) for p in gen.wall_pieces(layout)]
    boxes += [gen.door_panel_box(layout, d) for d in layout["doors"] if gen.is_exterior(d)]
    for rid, (x, y, _) in goals.items():
        assert min(_dist_to_box((x, y), b) for b in boxes) >= MIN_WALL_CLEARANCE, rid


def test_rectangular_room_goal_is_its_center(layout, goals):
    for r in layout["rooms"]:
        if len(r["polygon"]) != 4:
            continue
        cx, cy = gen.centroid(r["polygon"])
        x, y, _ = goals[r["id"]]
        assert math.hypot(x - cx, y - cy) <= rg.GRID, r["id"]


def test_lr_goal_is_inside_the_l_shape(goals, layout):
    lr = next(r for r in layout["rooms"] if r["id"] == "LR")
    x, y, clearance = goals["LR"]
    assert gen.point_in_polygon((x, y), lr["polygon"])
    assert clearance == pytest.approx(rg.boundary_distance((x, y), lr["polygon"]), abs=1e-3)
    assert clearance >= 1.8  # the 3.7 m wide part of LR allows ~1.85 m


def test_goal_clearance_is_maximal_on_the_grid():
    # 4 x 2 m rectangle: best clearance is 1.0 m, reached at the center.
    x, y, c = rg.room_goal([[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0]])
    assert c == pytest.approx(0.975, abs=1e-6)  # nearest cell center is 0.025 m off the midline
    assert math.hypot(x - 2.0, y - 1.0) <= 0.05


# ----------------------------------------------------------------- Nav2 params (D-061)
WAFFLE_MAX_V, WAFFLE_MAX_W = 0.26, 1.82
STAMPED_NODES = ["controller_server", "behavior_server", "velocity_smoother",
                 "collision_monitor", "docking_server"]


@pytest.fixture(scope="module")
def params():
    return yaml.safe_load((PKG / "config" / "nav2_params.yaml").read_text(encoding="utf-8"))


def _p(params, node):
    return params[node]["ros__parameters"]


def _costmap(params, name):
    return params[name][name]["ros__parameters"]


def test_amcl_starts_at_layout_robot_start(params, layout):
    amcl = _p(params, "amcl")
    s = layout["robot_start"]
    assert amcl["set_initial_pose"] is True
    pose = amcl["initial_pose"]
    assert (pose["x"], pose["y"], pose["yaw"]) == pytest.approx((s["x"], s["y"], s["yaw"]))
    assert pose["z"] == 0.0


def test_amcl_laser_range_matches_lidar(params):
    assert _p(params, "amcl")["laser_max_range"] == 3.5


def test_velocity_limits_match_waffle(params):
    mppi = _p(params, "controller_server")["FollowPath"]
    vs = _p(params, "velocity_smoother")
    assert mppi["vx_max"] == WAFFLE_MAX_V and mppi["vx_min"] == -WAFFLE_MAX_V
    assert mppi["wz_max"] == WAFFLE_MAX_W
    assert vs["max_velocity"] == [WAFFLE_MAX_V, 0.0, WAFFLE_MAX_W]
    assert vs["min_velocity"] == [-WAFFLE_MAX_V, 0.0, -WAFFLE_MAX_W]


def test_cmd_vel_is_stamped_everywhere(params):
    for node in STAMPED_NODES:
        assert _p(params, node)["enable_stamped_cmd_vel"] is True, node


def test_robot_fits_through_every_open_door(params, layout):
    # The lethal + inscribed zone around each wall end is robot_radius (rounded up to whole
    # cells); the remaining free corridor through the clear opening must be positive.
    t = layout["house"]["wall_thickness"]
    narrowest = min(d["width"] - t for d in layout["doors"] if not gen.is_exterior(d))
    for name in ("local_costmap", "global_costmap"):
        cm = _costmap(params, name)
        r = math.ceil(cm["robot_radius"] / cm["resolution"]) * cm["resolution"]
        assert narrowest - 2 * r >= 0.3, (name, narrowest, r)


def test_costmaps_use_the_map_frame_conventions(params):
    assert _costmap(params, "global_costmap")["global_frame"] == "map"
    assert "static_layer" in _costmap(params, "global_costmap")["plugins"]
    assert _p(params, "amcl")["global_frame_id"] == "map"
    assert _p(params, "amcl")["scan_topic"] == "scan"


def test_room_tour_default_order_covers_every_room(layout):
    text = (SCRIPTS / "room_tour.py").read_text(encoding="utf-8")
    start = text.index("DEFAULT_ORDER = ")
    order = ast.literal_eval(text[start + len("DEFAULT_ORDER = "):text.index("\n", start)])
    assert sorted(order) == sorted(r["id"] for r in layout["rooms"])
