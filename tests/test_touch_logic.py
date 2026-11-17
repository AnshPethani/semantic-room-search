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
W, H = 640, 360  # depth image size (D-097)


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(PKG / "layout" / "house_layout.yaml")


@pytest.fixture(scope="module")
def targets(layout):
    catalog = ho.load_yaml(PKG / "objects" / "catalog.yaml")
    return ho.place_objects(layout, catalog,
                            ho.load_yaml(PKG / "objects" / "scenarios" / "demo.yaml"))


def _render(pose, target, radius, height):
    """Depth image of one upright cylinder on the floor, as the camera at `pose` sees it."""
    cam, yaw, f = tl.camera_position(pose), pose[2], tl.focal_px(W)

    def depth_at(u, v):
        floor = tl.floor_depth(v, W, H)
        a = math.atan((W / 2 - (u + 0.5)) / f)
        dx, dy = math.cos(yaw + a), math.sin(yaw + a)
        ox, oy = cam[0] - target[0], cam[1] - target[1]
        b = ox * dx + oy * dy
        disc = b * b - (ox * ox + oy * oy - radius * radius)
        if disc >= 0 and -b - math.sqrt(disc) > 0:
            z = (-b - math.sqrt(disc)) * math.cos(a)          # along the camera axis
            hgt = tl.CAMERA_HEIGHT - z * ((v + 0.5) - H / 2) / f
            if 0.0 <= hgt <= height and z < floor:
                return z
        return floor  # floor below the horizon, nothing (inf) above it
    return depth_at


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
    link = next(lk for lk in model.iter("link") if lk.get("name") == "camera_rgb_frame")
    cx, cy, cz = (float(v) for v in link.find("pose").text.split()[:3])
    assert tl.CAMERA_OFFSET == pytest.approx((cx, cy))
    # The model origin rests on the wheels: wheel axle height minus wheel radius below it.
    wheel = next(c for c in model.iter("collision") if c.get("name") == "wheel_left_collision")
    origin_height = float(wheel.find("geometry/cylinder/radius").text) - float(
        wheel.find("pose").text.split()[2])
    assert tl.CAMERA_HEIGHT == pytest.approx(cz + origin_height)


def test_floor_depth_matches_the_measured_floor():
    # The first runs read 0.37 m at the bottom of the image with nothing in front.
    assert tl.floor_depth(H - 1, W, H) == pytest.approx(0.369, abs=0.002)
    assert tl.floor_depth(0, W, H) == math.inf and tl.floor_depth(H // 2 - 1, W, H) == math.inf
    assert tl.floor_depth(250, W, H) > tl.floor_depth(300, W, H)  # lower rows: closer floor


# ----------------------------------------------------------------- helpers
def test_bearing_error_sign_and_wrap():
    assert tl.bearing_error((0, 0, 0), (1, 0)) == pytest.approx(0)
    assert tl.bearing_error((0, 0, 0), (0, 1)) == pytest.approx(math.pi / 2)   # left
    assert tl.bearing_error((0, 0, 0), (0, -1)) == pytest.approx(-math.pi / 2)  # right
    assert tl.bearing_error((0, 0, 3.0), (-1, -0.01)) == pytest.approx(
        math.atan2(-0.01, -1) - 3.0 + 2 * math.pi)


def test_gap_is_front_face_to_footprint():
    assert tl.gap((0, 0, 0), (1.0, 0), 0.1) == pytest.approx(1.0 - 0.1 - tl.BODY_FRONT)


def test_transfer_keeps_the_robot_relative_position():
    pose_map, pose_odom = (3.0, 2.0, 0.7), (-1.0, 0.5, -2.0)
    point = (3.4, 2.3)
    moved = tl.transfer(point, pose_map, pose_odom)
    assert math.dist(moved, pose_odom[:2]) == pytest.approx(math.dist(point, pose_map[:2]))
    assert tl.bearing_error(pose_odom, moved) == pytest.approx(tl.bearing_error(pose_map, point))
    assert tl.transfer(moved, pose_odom, pose_map) == pytest.approx(point)


def test_camera_bearing_accounts_for_the_off_center_camera():
    # Target straight ahead of the robot center: the camera (4.7 cm to the right) sees it to
    # the left, more so up close. Ignoring this put the first depth band beside the bottle.
    near = tl.camera_bearing((0, 0, 0), (0.25, 0))
    far = tl.camera_bearing((0, 0, 0), (5.0, 0))
    assert near > far > 0
    assert tl.column_of(near, W) < W / 2 - P.band_px / 2
    for yaw in (0.0, 1.0, -2.5):  # on the camera's own axis the bearing is zero
        cx, cy = tl.camera_position((0, 0, yaw))
        tgt = (cx + 2 * math.cos(yaw), cy + 2 * math.sin(yaw))
        assert tl.camera_bearing((0, 0, yaw), tgt) == pytest.approx(0, abs=1e-9)


# ----------------------------------------------------------------- depth image
def test_floor_alone_is_not_an_object():
    floor_only = _render((0, 0, 0), (50, 50), 0.03, 0.2)  # target far outside the view
    assert tl.nearest_object(floor_only, W, H, W // 2) is None


def test_nearest_object_finds_the_target_not_the_floor():
    pose, target, r = (0.0, 0.0, 0.0), (0.5, -0.047), 0.035  # on the camera axis
    hit = tl.nearest_object(_render(pose, target, r, 0.25), W, H, W // 2)
    true_depth = target[0] - r - tl.CAMERA_OFFSET[0]
    assert hit is not None and hit.depth == pytest.approx(true_depth, abs=0.005)
    assert abs(hit.u - W / 2) <= P.stride_px


def test_near_side_hidden_depths():
    # Banana top edge 0.04 m: its near side leaves the image at ~0.24 m.
    assert tl.near_side_hidden_below(0.04, W, H) == pytest.approx(0.242, abs=0.002)
    assert tl.near_side_hidden_below(0.25, W, H) == 0.0   # bottle: taller than the camera
    catalog = ho.load_yaml(PKG / "objects" / "catalog.yaml")["classes"]
    assert tl.near_side_height(catalog["banana"]) == pytest.approx(0.04)
    assert tl.near_side_height(catalog["bottle"]) == pytest.approx(0.25)
    assert tl.near_side_height(catalog["apple"]) == pytest.approx(0.04)  # sphere: its middle


def test_low_object_whose_near_side_is_hidden_gives_no_sighting():
    # A banana 0.2 m ahead: its near side is below the image and only its far part shows.
    # Using that would push the estimate away (first test run: robot ended 1 cm inside it).
    pose, r, h = (0.0, 0.0, 0.0), 0.092, 0.04
    near = (tl.CAMERA_OFFSET[0] + 0.2 + r, tl.CAMERA_OFFSET[1])
    est, depth = tl.track(pose, near, r, h, _render(pose, near, r, h), W, H)
    assert depth is None and est == near
    # The same object farther away is fully in view and is used.
    far = (tl.CAMERA_OFFSET[0] + 0.45 + r, tl.CAMERA_OFFSET[1])
    est, depth = tl.track(pose, far, r, h, _render(pose, far, r, h), W, H)
    assert depth == pytest.approx(0.45, abs=0.01)


def test_observed_target_recovers_the_center():
    pose, r = (1.0, 2.0, 0.4), 0.08
    target = tl.to_world(pose, 0.6, 0.1)  # off the camera axis
    hit = tl.nearest_object(_render(pose, target, r, 0.06), W, H,
                            tl.column_of(tl.camera_bearing(pose, target), W))
    assert hit is not None
    assert math.dist(tl.observed_target(pose, hit, W, r), target) < 0.02


def test_update_target_accepts_near_and_ignores_far_sightings():
    est = (1.0, 1.0)
    new, ok = tl.update_target(est, (1.1, 1.0))
    assert ok and new == pytest.approx((1.0 + P.blend * 0.1, 1.0))
    same, ok = tl.update_target(est, (1.0 + P.max_jump + 0.01, 1.0))
    assert not ok and same == est
    assert tl.update_target(est, None) == (est, False)


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


# ----------------------------------------------------------------- servo and back-off steps
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


# ----------------------------------------------------------------- closed loop
def _drive(pose, step, dt):
    x, y, yaw = pose
    return (x + step.v * math.cos(yaw) * dt, y + step.v * math.sin(yaw) * dt, yaw + step.w * dt)


@pytest.mark.parametrize("heading_offset", [0.0, 0.4, -0.6])
def test_simulated_approach_without_camera(layout, targets, heading_offset):
    """Exact estimate, no camera or bumper: the gap stop must end close and facing."""
    dt = 0.05
    for o in targets:
        txy, r = (o["x"], o["y"]), o["radius"]
        x, y, yaw = tl.standoff_candidates(layout, txy, r, (1.65, 7.5))[0]
        pose = (x, y, yaw + heading_offset)
        for _ in range(int(60 / dt)):
            s = tl.servo_step(pose, txy, r, o["name"], set(), None)
            if s.done:
                break
            pose = _drive(pose, s, dt)
        assert s.done and s.outcome == "gap", o["name"]
        assert 0.0 <= tl.gap(pose, txy, r) <= P.gap_stop, o["name"]
        assert abs(tl.bearing_error(pose, txy)) <= P.facing_tol, o["name"]


@pytest.mark.parametrize("name,radius,height,outcome,max_gap", [
    ("bottle", 0.035, 0.25, "depth", 0.15),           # tall: seen all the way; proposal 0.15
    ("banana", 0.092, 0.04, "gap", P.gap_stop + 0.02),  # low: drops out of view up close
])
def test_simulated_approach_corrects_an_amcl_error(name, radius, height, outcome, max_gap):
    """The starting estimate is 0.11 m too close and 0.04 m to the side (like AMCL in the
    first runs); depth sightings must correct it before the stop."""
    dt = 0.05
    true_target = (2.0, 1.0)
    pose = (true_target[0] - (radius + tl.STANDOFF), true_target[1], 0.0)  # standoff, facing
    est = (true_target[0] - 0.11, true_target[1] + 0.04)
    sightings = 0
    for _ in range(int(60 / dt)):
        est, depth = tl.track(pose, est, radius, height,
                              _render(pose, true_target, radius, height), W, H)
        sightings += depth is not None
        s = tl.servo_step(pose, est, radius, name, set(), depth)
        if s.done:
            break
        pose = _drive(pose, s, dt)
    assert s.done and s.outcome == outcome
    assert sightings > 5
    true_gap = tl.gap(pose, true_target, radius)
    assert 0.0 <= true_gap <= max_gap, true_gap
    assert abs(tl.bearing_error(pose, true_target)) <= P.facing_tol
