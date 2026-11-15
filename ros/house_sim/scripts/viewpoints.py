"""Search viewpoints: 1-3 per room from which a 360 deg camera turn sees the room (D-080, D-081).

ROS-free. generate_house.py stores the result in the scene graph as the optional per-room
field "viewpoints" ([[x, y], ...]); the room-order planner drives to them and turns in place.

Coverage model: a floor point is seen from a viewpoint if it is within `camera_range` and the
straight line to it stays inside the room polygon. Floor points are sampled on a grid
(`target_grid`) at least half a wall thickness + 0.05 m from the wall center-lines.
Candidate viewpoints are grid points (`candidate_grid`) at least `wall_clearance` from the wall
surfaces, so the robot can turn in place there.

Selection: the fewest viewpoints (1..max_per_room) that see every floor sample. Among those,
the set that still covers the room with the smallest range (tried in 0.25 m steps up to
camera_range), so each viewpoint sits near the middle of the area it covers; then the set
whose viewpoint closest to a wall is farthest from it; then grid order.
"""
from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_house import edges, point_in_polygon, polygon_rects  # noqa: E402
from room_goals import boundary_distance  # noqa: E402

TARGET_MARGIN = 0.05  # floor samples start this far beyond the wall surface
RADIUS_STEP = 0.25
_EPS = 1e-9


class ViewpointError(ValueError):
    """A room cannot be covered with the allowed number of viewpoints."""


# ---------------------------------------------------------------- visibility
def _orient(p, q, r):
    v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return 0 if abs(v) <= _EPS else (1 if v > 0 else -1)


def _on_segment(p, a, b):
    return (min(a[0], b[0]) - _EPS <= p[0] <= max(a[0], b[0]) + _EPS
            and min(a[1], b[1]) - _EPS <= p[1] <= max(a[1], b[1]) + _EPS)


def segments_intersect(p1, p2, p3, p4):
    """True if closed segments p1p2 and p3p4 share a point (touching counts)."""
    o1, o2 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    o3, o4 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and _on_segment(p3, p1, p2)) or (o2 == 0 and _on_segment(p4, p1, p2))
            or (o3 == 0 and _on_segment(p1, p3, p4)) or (o4 == 0 and _on_segment(p2, p3, p4)))


def visible(v, q, polygon):
    """True if the segment v-q does not touch the room boundary (both points inside)."""
    return not any(segments_intersect(v, q, a, b) for a, b in edges(polygon))


def _is_convex(polygon):
    n = len(polygon)
    signs = {_orient(polygon[i], polygon[(i + 1) % n], polygon[(i + 2) % n]) for i in range(n)}
    return len(signs - {0}) <= 1


# ---------------------------------------------------------------- sampling
def grid_points(polygon, step, min_clearance):
    """Centers of a grid (centered on the polygon's bounding box) that lie inside the polygon
    and at least `min_clearance` from its boundary, in x-major order."""
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    nx, ny = math.floor(w / step + _EPS), math.floor(h / step + _EPS)
    x0 = min(xs) + (w - nx * step) / 2
    y0 = min(ys) + (h - ny * step) / 2
    out = []
    for i in range(nx):
        for j in range(ny):
            p = (x0 + (i + 0.5) * step, y0 + (j + 0.5) * step)
            inside = point_in_polygon(p, polygon)
            if inside and boundary_distance(p, polygon) >= min_clearance - _EPS:
                out.append(p)
    return out


def _radii(camera_range):
    out, r = [], 1.0
    while r < camera_range - _EPS:
        out.append(r)
        r += RADIUS_STEP
    out.append(camera_range)
    return out


# ---------------------------------------------------------------- selection
def room_viewpoints(polygon, cfg, wall_thickness):
    """Sorted list of (x, y) viewpoints for one room. Raises ViewpointError."""
    targets = grid_points(polygon, cfg["target_grid"], wall_thickness / 2 + TARGET_MARGIN)
    cands = grid_points(polygon, cfg["candidate_grid"],
                        wall_thickness / 2 + cfg["wall_clearance"])
    if not targets or not cands:
        raise ViewpointError("room is too small for a viewpoint")

    dist = [[math.hypot(c[0] - q[0], c[1] - q[1]) for q in targets] for c in cands]
    seen = None
    if not _is_convex(polygon):
        # Two points in the same rectangle of the room's decomposition always see each other;
        # only pairs in different rectangles need the boundary test.
        rects = polygon_rects(polygon)

        def rect_of(p):
            return next((k for k, (x0, y0, x1, y1) in enumerate(rects)
                         if x0 <= p[0] <= x1 and y0 <= p[1] <= y1), None)

        tr = [rect_of(q) for q in targets]
        seen = []
        for c in cands:
            cr = rect_of(c)
            seen.append([(cr is not None and cr == tr[j]) or visible(c, q, polygon)
                         for j, q in enumerate(targets)])
    clear = [boundary_distance(c, polygon) for c in cands]
    full = (1 << len(targets)) - 1
    masks_at = {}

    def masks(radius):
        if radius not in masks_at:
            masks_at[radius] = [
                sum(1 << j for j, d in enumerate(dist[i])
                    if d <= radius + _EPS and (seen is None or seen[i][j]))
                for i in range(len(cands))]
        return masks_at[radius]

    for k in range(1, cfg["max_per_room"] + 1):
        for radius in _radii(cfg["camera_range"]):
            m = masks(radius)
            best_key, best = None, None
            for combo in itertools.combinations(range(len(cands)), k):
                covered = 0
                for i in combo:
                    covered |= m[i]
                if covered != full:
                    continue
                key = min(clear[i] for i in combo)
                if best_key is None or key > best_key + _EPS:
                    best_key, best = key, combo
            if best is not None:
                return sorted((round(cands[i][0], 3), round(cands[i][1], 3)) for i in best)
    raise ViewpointError(f"needs more than {cfg['max_per_room']} viewpoints at camera range "
                         f"{cfg['camera_range']} m")


def layout_viewpoints(layout):
    """{room id: [[x, y], ...]} for every room of a house layout."""
    cfg = layout["viewpoints"]
    t = layout["house"]["wall_thickness"]
    out = {}
    for r in layout["rooms"]:
        try:
            out[r["id"]] = [list(p) for p in room_viewpoints(r["polygon"], cfg, t)]
        except ViewpointError as exc:
            raise ViewpointError(f"room {r['id']}: {exc}") from exc
    return out
