"""Approach-and-touch logic: standoff poses, depth-based target tracking, servo (D-098).

ROS-free (standard library and the sibling helper modules), so it is tested with plain pytest.
touch_target.py wraps it in a ROS node (Nav2 for the standoff, then this servo at ~20 Hz).

Frames: the standoff uses the map frame (AMCL). The final approach runs in the odom frame:
wheel odometry is accurate over the last half meter, AMCL is not (it was 4-11 cm off in the
first runs). The target estimate starts from its known map position, moved into the odom frame
once, and is corrected whenever the depth camera sees the target where it is expected.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_house import (  # noqa: E402
    door_panel_box,
    is_exterior,
    point_in_polygon,
    wall_box,
    wall_pieces,
)
from house_objects import dist_to_box  # noqa: E402

# Robot geometry (models/turtlebot3_waffle_bumper/model.sdf; tested against it).
BODY_FRONT = 0.0685              # m, front face of base_collision ahead of base_link
CAMERA_HFOV = 1.02974            # rad, RGB and depth camera horizontal field of view
CAMERA_OFFSET = (0.069, -0.047)  # m, camera (x forward, y left) relative to base_link
CAMERA_HEIGHT = 0.117            # m above the floor (camera link 0.107 + base 0.01); the
                                 # bottom image row then sees the floor at 0.369 m, as measured

STANDOFF = 0.5           # proposal: Nav2 brings the robot to 0.5 m from the target
STANDOFF_DIRECTIONS = 16
STANDOFF_WALL_CLEARANCE = 0.32   # m from wall surfaces: robot radius 0.22 + 0.1 margin


@dataclass(frozen=True)
class ServoParams:
    """Gains and thresholds of the final approach."""

    v_max: float = 0.08          # m/s, slow final approach
    v_min: float = 0.03          # m/s, keeps moving until contact
    k_v: float = 0.4             # 1/s, speed per meter of remaining gap
    w_max: float = 0.5           # rad/s
    k_w: float = 1.5             # 1/s, turn rate per radian of bearing error
    align_tol: float = 0.10      # rad; turn in place above this bearing error
    facing_tol: float = 0.26     # rad (~15 deg); "facing the target" for the stop rules
    depth_stop: float = 0.14     # m; proposal: "depth reading below 0.15 m". 1 cm margin: the
                                 # true gap is slightly larger than the depth when not square-on
    gap_stop: float = 0.05       # m, gap from the tracked estimate (target out of view)
    band_px: int = 60            # half width of the image search band around the target
    stride_px: int = 4           # pixel step of the search (rows and columns)
    floor_margin: float = 0.03   # m; a pixel this much closer than the floor is an object
    hidden_margin: float = 0.02  # m; ignore sightings closer than the near-side-hidden depth
                                 # plus this (only the far part of a low object is in view)
    max_jump: float = 0.25       # m; depth sightings farther than this from the estimate
                                 # are something else (wall, clutter) and are ignored
    blend: float = 0.5           # weight of a new sighting in the target estimate
    back_v: float = 0.05         # m/s, reverse speed after the touch
    back_off_gap: float = 0.30   # m, back off until the gap is this large (out of the
                                 # target's lethal costmap zone, so Nav2 can plan again)


DEFAULT_PARAMS = ServoParams()


@dataclass(frozen=True)
class ServoStep:
    v: float
    w: float
    done: bool
    outcome: str  # "" while running; "contact", "depth", "gap" (success) or "blocked:<model>"


@dataclass(frozen=True)
class DepthHit:
    depth: float  # m along the camera axis
    u: int        # image column


# ---------------------------------------------------------------- geometry
def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def bearing_error(pose, target):
    """Angle from the robot's heading to the target, positive = target to the left."""
    x, y, yaw = pose
    return wrap(math.atan2(target[1] - y, target[0] - x) - yaw)


def to_world(pose, dx, dy):
    """Point (dx forward, dy left) in the robot frame -> the frame of pose."""
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return (x + dx * c - dy * s, y + dx * s + dy * c)


def camera_position(pose):
    return to_world(pose, *CAMERA_OFFSET)


def camera_bearing(pose, target):
    """Bearing of the target as seen from the camera, which sits off the robot's center line.

    This, not bearing_error, decides where the target appears in the image.
    """
    cx, cy = camera_position(pose)
    return wrap(math.atan2(target[1] - cy, target[0] - cx) - pose[2])


def gap(pose, target, radius):
    """Distance from the robot's front face to the target's footprint circle."""
    return math.hypot(target[0] - pose[0], target[1] - pose[1]) - radius - BODY_FRONT


def transfer(point, pose_from, pose_to):
    """Re-express a point given in pose_from's frame so that it keeps the same position
    relative to the robot, with the robot at pose_to (e.g. map -> odom at one instant)."""
    x0, y0, a0 = pose_from
    dx, dy = point[0] - x0, point[1] - y0
    rx = dx * math.cos(a0) + dy * math.sin(a0)       # robot-relative
    ry = -dx * math.sin(a0) + dy * math.cos(a0)
    return to_world(pose_to, rx, ry)


# ---------------------------------------------------------------- depth image
def focal_px(width, hfov=CAMERA_HFOV):
    return (width / 2) / math.tan(hfov / 2)


def floor_depth(v, width, height, cam_h=CAMERA_HEIGHT, hfov=CAMERA_HFOV):
    """Depth along the camera axis at which image row v sees the floor; inf above the horizon.
    Pixels are square, so the vertical focal length equals the horizontal one."""
    below = (v + 0.5) - height / 2
    if below <= 0:
        return math.inf
    return cam_h * focal_px(width, hfov) / below


def column_of(bearing, width, hfov=CAMERA_HFOV):
    """Image column of a camera bearing (positive = left = smaller column)."""
    b = max(-hfov / 2, min(hfov / 2, bearing))
    return int(round(width / 2 - focal_px(width, hfov) * math.tan(b)))


def nearest_object(depth_at, width, height, u_center, params=None):
    """Closest non-floor pixel in a column band around u_center, or None.

    depth_at(u, v) returns the depth in meters (inf or nan for no return). A pixel counts as
    an object if it is clearly closer than the floor would be in its row.
    """
    params = params or DEFAULT_PARAMS
    best = None
    u0 = max(0, u_center - params.band_px)
    u1 = min(width, u_center + params.band_px + 1)
    for u in range(u0, u1, params.stride_px):
        for v in range(0, height, params.stride_px):
            d = depth_at(u, v)
            if not (d > 0 and math.isfinite(d)):
                continue
            if d >= floor_depth(v, width, height) - params.floor_margin:
                continue
            if best is None or d < best.depth:
                best = DepthHit(d, u)
    return best


def near_side_hidden_below(near_height, width, height, cam_h=CAMERA_HEIGHT, hfov=CAMERA_HFOV):
    """Depth below which the target's near side (at near_height above the floor) is below the
    bottom of the image. 0 for parts at or above the camera height (never hidden)."""
    if near_height >= cam_h:
        return 0.0
    return (cam_h - near_height) * focal_px(width, hfov) / (height / 2)


def near_side_height(spec):
    """Height of an object's point nearest to the camera: the top edge of a box or cylinder
    front face, the middle of a sphere."""
    if spec["shape"] == "sphere":
        return spec["radius"]
    return spec["size"][2] if spec["shape"] == "box" else spec["length"]


def observed_target(pose, hit, width, radius, hfov=CAMERA_HFOV):
    """Target center implied by the nearest depth hit on it (same frame as pose).

    Depth is measured along the camera axis, so the nearest pixel of a round object is the
    point of its footprint closest to the camera along that axis; the center lies one radius
    further along the camera axis from it, not along the pixel's ray.
    """
    a = math.atan((width / 2 - (hit.u + 0.5)) / focal_px(width, hfov))
    xc = hit.depth + radius                      # camera frame: x forward, y left
    yc = hit.depth * math.tan(a)
    return to_world(pose, CAMERA_OFFSET[0] + xc, CAMERA_OFFSET[1] + yc)


def update_target(estimate, observation, params=None):
    """Blend a sighting into the estimate if it is plausibly the same object.
    Returns (new estimate, accepted)."""
    params = params or DEFAULT_PARAMS
    if observation is None or math.dist(estimate, observation) > params.max_jump:
        return estimate, False
    b = params.blend
    x = (1 - b) * estimate[0] + b * observation[0]
    y = (1 - b) * estimate[1] + b * observation[1]
    return (x, y), True


def track(pose, estimate, radius, near_height, depth_at, width, height, params=None):
    """One tracking step: look for the target near its expected column and update the estimate.

    near_height: height of the target's point nearest to the camera (near_side_height).
    A hit closer than the depth at which that point leaves the image is the far part of a
    low object, not its near side, and is ignored. Returns (estimate, accepted depth or None).
    """
    params = params or DEFAULT_PARAMS
    if depth_at is None:
        return estimate, None
    u = column_of(camera_bearing(pose, estimate), width)
    hit = nearest_object(depth_at, width, height, u, params)
    hidden = near_side_hidden_below(near_height, width, height)
    if hit is None or (hidden > 0 and hit.depth < hidden + params.hidden_margin):
        return estimate, None
    new, ok = update_target(estimate, observed_target(pose, hit, width, radius), params)
    return (new, hit.depth) if ok else (estimate, None)


# ---------------------------------------------------------------- standoff
def standoff_candidates(layout, target, radius, robot_xy, standoff=STANDOFF,
                        n=STANDOFF_DIRECTIONS, clearance=STANDOFF_WALL_CLEARANCE):
    """Poses `standoff` m in front of the target's footprint, facing it, that are inside a
    room and clear of the known walls; closest to `robot_xy` first. Clutter is not known here;
    Nav2 rejects or fails a blocked candidate and the caller tries the next one."""
    t = layout["house"]["wall_thickness"]
    walls = [wall_box(p, t) for p in wall_pieces(layout)]
    walls += [door_panel_box(layout, d) for d in layout["doors"] if is_exterior(d)]
    r = radius + standoff
    out = []
    for k in range(n):
        a = 2 * math.pi * k / n
        # Round first, so the checks below apply to exactly the pose that is returned.
        x = round(target[0] + r * math.cos(a), 3)
        y = round(target[1] + r * math.sin(a), 3)
        if not any(point_in_polygon((x, y), rm["polygon"]) for rm in layout["rooms"]):
            continue
        if min(dist_to_box((x, y), b) for b in walls) < clearance:
            continue
        yaw = math.atan2(target[1] - y, target[0] - x)
        out.append((x, y, round(yaw, 4)))
    out.sort(key=lambda p: (math.hypot(p[0] - robot_xy[0], p[1] - robot_xy[1]), p))
    return out


# ---------------------------------------------------------------- control
def back_off_step(pose, target, radius, target_name, contacts, params=None):
    """One step of reversing straight away from the target after a touch.

    Done when the gap reaches back_off_gap ("clear") or the body touches something other
    than the target ("blocked:<model>"); the target itself may still be in contact.
    """
    params = params or DEFAULT_PARAMS
    others = sorted(contacts - {target_name})
    if others:
        return ServoStep(0.0, 0.0, True, f"blocked:{others[0]}")
    if gap(pose, target, radius) >= params.back_off_gap:
        return ServoStep(0.0, 0.0, True, "clear")
    return ServoStep(-params.back_v, 0.0, False, "")


def servo_step(pose, target, radius, target_name, contacts, depth, params=None):
    """One control step of the final approach.

    pose and target in the same frame (odom during the approach); target is the tracked
    estimate. contacts: Gazebo model names touching the robot body (from /bumper).
    depth: the target's depth from this cycle's accepted sighting, or None.
    """
    params = params or DEFAULT_PARAMS
    if target_name in contacts:
        return ServoStep(0.0, 0.0, True, "contact")
    others = sorted(contacts - {target_name})
    if others:
        return ServoStep(0.0, 0.0, True, f"blocked:{others[0]}")

    e = bearing_error(pose, target)
    g = gap(pose, target, radius)
    facing = abs(e) <= params.facing_tol
    if facing and depth is not None and depth <= params.depth_stop:
        return ServoStep(0.0, 0.0, True, "depth")
    if facing and g <= params.gap_stop:
        return ServoStep(0.0, 0.0, True, "gap")

    w = max(-params.w_max, min(params.w_max, params.k_w * e))
    if abs(e) > params.align_tol:
        return ServoStep(0.0, w, False, "")
    v = max(params.v_min, min(params.v_max, params.k_v * g))
    return ServoStep(v, w, False, "")
