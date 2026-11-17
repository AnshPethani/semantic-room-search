"""Ground-truth check of a touch from Gazebo's robot pose (D-094).

ROS-free. touch_target.py --truth calls `gz model -m waffle -p` after the touch and uses this
module to measure the true gap from the robot's front face to the object's real footprint
(a rotated rectangle for boxes, a circle for cylinders and spheres) and whether the robot faces
that point. Proposal criterion: contact, or within 0.15 m while facing the target.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from touch_logic import BODY_FRONT, bearing_error, to_world  # noqa: E402

TOUCH_TOL = 0.15     # m, proposal
FACING_TOL = math.radians(15.0)

_TRIPLE = re.compile(r"\[\s*(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s*\]")
_RESULT = re.compile(r"^RESULT (\S+): (SUCCEEDED|FAILED) \(([^)]*)\)")
_TRUTH = re.compile(r"^TRUTH (\S+): gap (-?[\d.]+) m, bearing (-?[\d.]+) deg, (PASS|FAIL)")


def parse_gz_pose(text):
    """(x, y, yaw) from `gz model -m <name> -p` output, or None."""
    triples = _TRIPLE.findall(text)
    if len(triples) < 2:
        return None
    x, y, _ = (float(v) for v in triples[0])
    return (x, y, float(triples[1][2]))


def nearest_footprint_point(point, center, spec, yaw):
    """Point of the object's footprint closest to `point` (the point itself if inside)."""
    if spec["shape"] == "box":
        hx, hy = spec["size"][0] / 2, spec["size"][1] / 2
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy = point[0] - center[0], point[1] - center[1]
        lx, ly = dx * c + dy * s, -dx * s + dy * c          # into the box frame
        lx, ly = max(-hx, min(hx, lx)), max(-hy, min(hy, ly))
        return (center[0] + lx * c - ly * s, center[1] + lx * s + ly * c)
    r = spec["radius"]
    d = math.dist(point, center)
    if d <= r:
        return point
    k = r / d
    return (center[0] + (point[0] - center[0]) * k, center[1] + (point[1] - center[1]) * k)


def true_touch(pose, center, spec, yaw):
    """(gap, bearing): distance from the robot's front-face center to the object's footprint,
    and the bearing from the robot's heading to that nearest point (radians)."""
    front = to_world(pose, BODY_FRONT, 0.0)
    q = nearest_footprint_point(front, center, spec, yaw)
    return math.dist(front, q), bearing_error(pose, q)


def touch_ok(gap, bearing):
    return gap <= TOUCH_TOL and abs(bearing) <= FACING_TOL


def parse_result(line):
    """(name, succeeded, outcome) from a touch_target RESULT line, or None."""
    m = _RESULT.match(line.strip())
    return (m.group(1), m.group(2) == "SUCCEEDED", m.group(3)) if m else None


def parse_truth(line):
    """(name, gap, bearing_deg, passed) from a touch_target TRUTH line, or None."""
    m = _TRUTH.match(line.strip())
    if not m:
        return None
    return (m.group(1), float(m.group(2)), float(m.group(3)), m.group(4) == "PASS")
