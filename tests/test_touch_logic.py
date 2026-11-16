"""ROS-free tests for the approach-and-touch logic (D-098)."""
import importlib.util
import math
import sys
import xml.etree.ElementTree as ET
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

P = tl.ServoParams()


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(PKG / "layout" / "house_layout.yaml")


@pytest.fixture(scope="module")
def targets(layout):
    catalog = ho.load_yaml(PKG / "objects" / "catalog.yaml")
    return ho.place_objects(layout, catalog,
                            ho.load_yaml(PKG / "objects" / "scenarios" / "demo.yaml"))


# ----------------------------------------------------------------- robot geometry
def test_geometry_constants_match_the_robot_model():
    model = ET.parse(PKG / "models" / "turtlebot3_waffle_bumper" / "model.sdf").getroot()
    col = next(c for c in model.iter("collision") if c.get("name") == "base_collision")
    x = float(col.find("pose").text.split()[0])
    sx = float(col.find("geometry/box/size").text.split()[0])
    assert tl.BODY_FRONT == pytest.approx(x + sx / 2)
    for name in ("camera", "depth_camera"):
        sensor = next(s for s in model.iter("sensor") if s.get("name") == name)
        assert float(sensor.find("camera/horizontal_fov").text) == pytest.approx(tl.CAMERA_HFOV)
    # Both cameras sit at the origin of link camera_rgb_frame (model frame = base_link in x, y).
    link = next(lk for lk in model.iter("link") if lk.get("name") == "camera_rgb_frame")
    x, y = (float(v) for v in link.find("pose").text.split()[:2])
    assert tl.CAMERA_OFFSET == pytest.approx((x, y))


def test_camera_bearing_accounts_for_the_off_center_camera():
    # Target straight ahead of the robot center: the camera (4.7 cm to the right) sees it to
    # the left, more so up close. This shift moved the bottle out of the first depth band.
    near = tl.camera_bearing((0, 0, 0), (0.25, 0))
    far = tl.camera_bearing((0, 0, 0), (5.0, 0))
    assert near > far > 0
    width = 640
    fx = (width / 2) / math.tan(tl.CAMERA_HFOV / 2)
    assert fx * math.tan(near) > P.depth_band_px      # outside a band centered on the image
    u0, u1 = tl.depth_columns(width, near)
    assert u0 <= width / 2 - fx * math.tan(near) <= u1   # inside the corrected band
    # On the camera's own axis the bearing is zero, for any heading.
    for yaw in (0.0, 1.0, -2.5):
        cx = tl.CAMERA_OFFSET[0] * math.cos(yaw) - tl.CAMERA_OFFSET[1] * math.sin(yaw)
        cy = tl.CAMERA_OFFSET[0] * math.sin(yaw) + tl.CAMERA_OFFSET[1] * math.cos(yaw)
        tgt = (cx + 2 * math.cos(yaw), cy + 2 * math.sin(yaw))
        assert tl.camera_bearing((0, 0, yaw), tgt) == pytest.approx(0, abs=1e-9)


# ----------------------------------------------------------------- helpers
def test_bearing_error_sign_and_wrap():
    assert tl.bearing_error((0, 0, 0), (1, 0)) == pytest.approx(0)
    assert tl.bearing_error((0, 0, 0), (0, 1)) == pytest.approx(math.pi / 2)   # left
    assert tl.bearing_error((0, 0, 0), (0, -1)) == pytest.approx(-math.pi / 2)  # right
    assert tl.bearing_error((0, 0, 3.0), (-1, -0.01)) == pytest.approx(
        math.atan2(-0.01, -1) - 3.0 + 2 * math.pi)


def test_gap_is_front_face_to_footprint():
    assert tl.gap((0, 0, 0), (1.0, 0), 0.1) == pytest.approx(1.0 - 0.1 - tl.BODY_FRONT)


def test_depth_columns_follow_the_target():
    width = 640
    u0, u1 = tl.depth_columns(width, 0.0)
    assert (u0 + u1) / 2 == pytest.approx(width / 2, abs=1)
    left = tl.depth_columns(width, 0.3)
    right = tl.depth_columns(width, -0.3)
    assert left[1] < u0 and right[0] > u1   # target to the left -> smaller u
    for e in (-2.0, 2.0):                   # outside the FOV: clamped to the image edge
        a, b = tl.depth_columns(width, e)
        assert 0 <= a < b <= width


# ----------------------------------------------------------------- standoff
def test_standoff_candidates_face_the_target_and_avoid_walls(layout, targets):
    t = layout["house"]["wall_thickness"]
    walls = [gen.wall_box(p, t) for p in gen.wall_pieces(layout)]
    for o in targets:
        txy = (o["x"], o["y"])
        cands = tl.standoff_candidates(layout, txy, o["radius"], (1.65, 7.5))
        assert cands, f"no standoff for {o['name']}"
        dists = [math.hypot(x - 1.65, y - 7.5) for x, y, _ in cands]
        assert dists == sorted(dists)
        for x, y, yaw in cands:
            assert math.hypot(x - txy[0], y - txy[1]) == pytest.approx(
                o["radius"] + tl.STANDOFF, abs=2e-3)
            assert abs(tl.bearing_error((x, y, yaw), txy)) < 1e-3
            assert min(ho.dist_to_box((x, y), b) for b in walls) >= tl.STANDOFF_WALL_CLEARANCE


# ----------------------------------------------------------------- servo step
def test_contact_with_target_succeeds_and_other_contact_fails():
    s = tl.servo_step((0, 0, 0), (1, 0), 0.05, "obj_cup_0", {"obj_cup_0"}, None)
    assert (s.done, s.outcome, s.v, s.w) == (True, "contact", 0.0, 0.0)
    s = tl.servo_step((0, 0, 0), (1, 0), 0.05, "obj_cup_0", {"house_walls"}, None)
    assert s.done and s.outcome == "blocked:house_walls"


def test_turns_in_place_when_misaligned():
    s = tl.servo_step((0, 0, 0), (0, 1), 0.05, "t", set(), None)
    assert not s.done and s.v == 0.0 and s.w == pytest.approx(P.w_max)
    s = tl.servo_step((0, 0, 0), (0, -1), 0.05, "t", set(), None)
    assert s.w == pytest.approx(-P.w_max)


def test_drives_slowly_when_aligned():
    s = tl.servo_step((0, 0, 0), (1, 0.01), 0.05, "t", set(), None)
    assert not s.done and P.v_min <= s.v <= P.v_max and s.w > 0


def test_depth_stop_only_when_facing():
    s = tl.servo_step((0, 0, 0), (0.5, 0), 0.05, "t", set(), 0.14)
    assert s.done and s.outcome == "depth"
    s = tl.servo_step((0, 0, 0), (0.0, 0.5), 0.05, "t", set(), 0.14)  # 90 deg off
    assert not s.done


def test_gap_stop():
    close = 0.05 + tl.BODY_FRONT + P.gap_stop - 0.001
    s = tl.servo_step((0, 0, 0), (close, 0), 0.05, "t", set(), None)
    assert s.done and s.outcome == "gap"


def test_back_off_reverses_until_clear():
    touching = (0.0, 0.0, 0.0), (0.05 + tl.BODY_FRONT + 0.03, 0.0)
    s = tl.back_off_step(*touching, 0.03, "t", {"t"})  # still touching the target: fine
    assert not s.done and s.v == pytest.approx(-P.back_v) and s.w == 0.0
    s = tl.back_off_step(*touching, 0.03, "t", {"clutter_box_0"})
    assert s.done and s.outcome == "blocked:clutter_box_0"
    far = (0.0, 0.0, 0.0), (P.back_off_gap + tl.BODY_FRONT + 0.03 + 0.01, 0.0)
    s = tl.back_off_step(*far, 0.03, "t", set())
    assert s.done and s.outcome == "clear"


def test_simulated_back_off_ends_clear_of_the_target():
    dt, pose, target, r = 0.05, (0.0, 0.0, 0.0), (0.15, 0.0), 0.035
    for _ in range(int(20 / dt)):
        s = tl.back_off_step(pose, target, r, "t", set())
        if s.done:
            break
        pose = (pose[0] + s.v * math.cos(pose[2]) * dt, pose[1] + s.v * math.sin(pose[2]) * dt,
                pose[2])
    assert s.outcome == "clear"
    assert P.back_off_gap <= tl.gap(pose, target, r) <= P.back_off_gap + P.back_v * dt + 1e-9
    # Out of the target's lethal zone in Nav2's costmap (robot radius 0.22 + target radius).
    assert math.dist(pose[:2], target) > 0.22 + r


# ----------------------------------------------------------------- closed loop
@pytest.mark.parametrize("heading_offset", [0.0, 0.4, -0.6])
def test_simulated_approach_from_every_standoff(layout, targets, heading_offset):
    """Unicycle model, no bumper or depth: the pose-based stop must end close and facing."""
    dt = 0.05
    for o in targets:
        txy, r = (o["x"], o["y"]), o["radius"]
        x, y, yaw = tl.standoff_candidates(layout, txy, r, (1.65, 7.5))[0]
        pose = (x, y, yaw + heading_offset)
        for _ in range(int(60 / dt)):
            s = tl.servo_step(pose, txy, r, o["name"], set(), None)
            if s.done:
                break
            px, py, pyaw = pose
            pose = (px + s.v * math.cos(pyaw) * dt, py + s.v * math.sin(pyaw) * dt,
                    pyaw + s.w * dt)
        assert s.done and s.outcome == "gap", o["name"]
        assert 0.0 <= tl.gap(pose, txy, r) <= P.gap_stop, o["name"]
        assert abs(tl.bearing_error(pose, txy)) <= P.facing_tol, o["name"]
