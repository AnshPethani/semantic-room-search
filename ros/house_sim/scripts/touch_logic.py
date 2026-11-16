"""Approach-and-touch logic: standoff poses and the final servo step (D-098).

ROS-free (standard library and the sibling helper modules), so it is tested with plain pytest.
touch_target.py wraps it in a ROS node (Nav2 for the standoff, then this servo at ~20 Hz).

Poses are (x, y, yaw) of base_link in the map frame; the target is its map-frame center (x, y)
and footprint radius (from the truth file / scenario, later from a detection).
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
BODY_FRONT = 0.0685      # m, front face of base_collision ahead of base_link
CAMERA_HFOV = 1.02974    # rad, RGB and depth camera horizontal field of view
CAMERA_OFFSET = (0.069, -0.047)  # m, camera (x forward, y left) relative to base_link

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
    depth_stop: float = 0.15     # m, proposal: stop when the depth reading is below 0.15 m
    gap_stop: float = 0.05       # m, pose-based safety stop (flat objects: no bumper, no depth)
    depth_band_px: int = 20      # half width of the depth column band around the target
    back_v: float = 0.05         # m/s, reverse speed after the touch
    back_off_gap: float = 0.30   # m, back off until the gap is this large (out of the
                                 # target's lethal costmap zone, so Nav2 can plan again)


@dataclass(frozen=True)
class ServoStep:
    v: float
    w: float
    done: bool
    outcome: str  # "" while running; "contact", "depth", "gap" (success) or "blocked:<model>"


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def bearing_error(pose, target):
    """Angle from the robot's heading to the target, positive = target to the left."""
    x, y, yaw = pose
    return wrap(math.atan2(target[1] - y, target[0] - x) - yaw)


def camera_bearing(pose, target):
    """Bearing of the target as seen from the camera, which sits off the robot's center line.

    This, not bearing_error, decides where the target appears in the image (D-098).
    """
    x, y, yaw = pose
    cx = x + CAMERA_OFFSET[0] * math.cos(yaw) - CAMERA_OFFSET[1] * math.sin(yaw)
    cy = y + CAMERA_OFFSET[0] * math.sin(yaw) + CAMERA_OFFSET[1] * math.cos(yaw)
    return wrap(math.atan2(target[1] - cy, target[0] - cx) - yaw)


def gap(pose, target, radius):
    """Estimated distance from the robot's front face to the target's footprint circle."""
    return math.hypot(target[0] - pose[0], target[1] - pose[1]) - radius - BODY_FRONT


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


DEFAULT_PARAMS = ServoParams()


def depth_columns(width, bearing_err, params=None, hfov=CAMERA_HFOV):
    """Column range [u0, u1) of the depth image where the target should appear.

    Image columns grow to the right; a target to the left (positive bearing) appears at
    smaller u. Rows are not limited: the floor is never closer than ~0.37 m in this camera.
    """
    params = params or DEFAULT_PARAMS
    fx = (width / 2) / math.tan(hfov / 2)
    u = width / 2 - fx * math.tan(max(-hfov / 2, min(hfov / 2, bearing_err)))
    u0 = max(0, int(round(u)) - params.depth_band_px)
    u1 = min(width, int(round(u)) + params.depth_band_px)
    return u0, u1


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


def servo_step(pose, target, radius, target_name, contacts, depth_min, params=None):
    """One control step of the final approach.

    contacts: Gazebo model names currently touching the robot body (from /bumper).
    depth_min: smallest valid depth in the target's column band, or None if unknown.
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
    if facing and depth_min is not None and depth_min <= params.depth_stop:
        return ServoStep(0.0, 0.0, True, "depth")
    if facing and g <= params.gap_stop:
        return ServoStep(0.0, 0.0, True, "gap")

    w = max(-params.w_max, min(params.w_max, params.k_w * e))
    if abs(e) > params.align_tol:
        return ServoStep(0.0, w, False, "")
    v = max(params.v_min, min(params.v_max, params.k_v * g))
    return ServoStep(v, w, False, "")
