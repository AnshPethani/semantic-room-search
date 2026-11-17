"""ROS-free tests for the touch ground-truth check (D-094) and the trial launch (D-093)."""
import importlib.util
import math
import sys
from pathlib import Path

import pytest

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
tl = _load("touch_logic")
tc = _load("touch_check")


@pytest.fixture(scope="module")
def catalog():
    return ho.load_yaml(PKG / "objects" / "catalog.yaml")["classes"]


# Output of `gz model -m waffle -p` after the verified banana run (2026-11-16).
GZ_BANANA = """Requesting state for world [house]...

Model: [81]
  - Name: waffle
  - Pose [ XYZ (m) ] [ RPY (rad) ]:
    [0.735365 0.726464 0.010008]
    [-0.000000 -0.005692 -1.977940]
"""


def test_parse_gz_pose():
    assert tc.parse_gz_pose(GZ_BANANA) == pytest.approx((0.735365, 0.726464, -1.977940))
    assert tc.parse_gz_pose("Requesting state for world [house]...") is None


def test_verified_banana_run_passes(catalog):
    # Banana: box 0.18 x 0.04 at (0.6, 0.6), yaw 0. Its corner (0.69, 0.62) is dead ahead.
    gap, bearing = tc.true_touch(tc.parse_gz_pose(GZ_BANANA), (0.6, 0.6), catalog["banana"], 0.0)
    assert gap == pytest.approx(0.047, abs=0.003)
    assert abs(math.degrees(bearing)) < 2.0
    assert tc.touch_ok(gap, bearing)


def test_verified_bottle_run_passes(catalog):
    # Gazebo pose after the bottle run (2026-11-16); bottle: cylinder r 0.035 at (0.6, 3.5).
    gap, bearing = tc.true_touch((0.839515, 3.504290, -3.120790), (0.6, 3.5),
                                 catalog["bottle"], 0.0)
    assert gap == pytest.approx(0.136, abs=0.003)
    assert tc.touch_ok(gap, bearing)


def test_box_footprint_uses_its_orientation():
    spec = {"shape": "box", "size": [0.4, 0.1, 0.1]}
    # Point 0.3 m along +y from the center: 0.25 m from the long side if the box lies along x,
    # 0.1 m from the short end if it is turned 90 degrees.
    assert math.dist((0, 0.3), tc.nearest_footprint_point((0, 0.3), (0, 0), spec, 0.0)) == \
        pytest.approx(0.25)
    assert math.dist((0, 0.3), tc.nearest_footprint_point((0, 0.3), (0, 0), spec, math.pi / 2)) \
        == pytest.approx(0.1)


def test_far_or_sideways_stops_fail(catalog):
    cup = catalog["cup"]
    gap, bearing = tc.true_touch((0.0, 0.0, 0.0), (0.5, 0.0), cup, 0.0)       # 0.39 m away
    assert not tc.touch_ok(gap, bearing)
    gap, bearing = tc.true_touch((0.0, 0.0, 0.0), (0.0, 0.2), cup, 0.0)       # beside it
    assert not tc.touch_ok(gap, bearing)


def test_parse_result_and_truth_lines():
    assert tc.parse_result("RESULT obj_banana_0: SUCCEEDED (gap); front-to-target gap 0.050 m") \
        == ("obj_banana_0", True, "gap")
    assert tc.parse_result("RESULT obj_cup_0: FAILED (no standoff reached)") == \
        ("obj_cup_0", False, "no standoff reached")
    assert tc.parse_truth("TRUTH obj_cup_0: gap 0.123 m, bearing -4.2 deg, PASS (Gazebo pose "
                          "1 2 3)") == ("obj_cup_0", 0.123, -4.2, True)
    assert tc.parse_result("    gap 0.2 m, bearing 0.0 deg") is None


# ----------------------------------------------------------------- trial launch (D-093)
def test_trial_launch_wires_world_objects_and_clutter():
    text = (PKG / "launch" / "trial.launch.py").read_text(encoding="utf-8")
    for arg in ("'scenario'", "'clutter_count'", "'clutter_seed'", "'spawn_delay'", "'gui'",
                "'rviz'"):
        assert f"DeclareLaunchArgument({arg}" in text, arg
    for included in ("house_nav.launch.py", "spawn_objects.launch.py",
                     "spawn_clutter.launch.py"):
        assert included in text
    assert "TimerAction" in text
