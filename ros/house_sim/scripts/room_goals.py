"""One navigation goal per room for the Nav2 room tour (D-063).

The goal is the interior point (on a 0.05 m grid of cell centers) that is farthest from the
room's polygon boundary, i.e. from the wall center-lines. Ties are broken by closeness to the
area centroid, so a rectangular room gets its center. Unlike the centroid, the result is always
inside the room, also for the L-shaped LR.

ROS-free (standard library + generate_house helpers). This is not the viewpoint generator:
viewpoints for the search come later and may replace these goals.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_house import centroid, edges, point_in_polygon  # noqa: E402

GRID = 0.05


def _point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def boundary_distance(p, polygon):
    return min(_point_segment_distance(p, a, b) for a, b in edges(polygon))


def room_goal(polygon, grid=GRID):
    """(x, y, clearance): the grid point inside `polygon` farthest from its boundary."""
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    x0, y0 = min(xs), min(ys)
    nx, ny = round((max(xs) - x0) / grid), round((max(ys) - y0) / grid)
    cx, cy = centroid(polygon)
    best_key, best = None, None
    for i in range(nx):
        for j in range(ny):
            p = (x0 + (i + 0.5) * grid, y0 + (j + 0.5) * grid)
            if not point_in_polygon(p, polygon):
                continue
            clearance = boundary_distance(p, polygon)
            key = (round(clearance, 6), -math.hypot(p[0] - cx, p[1] - cy))
            if best_key is None or key > best_key:
                best_key, best = key, (round(p[0], 3), round(p[1], 3), round(clearance, 3))
    if best is None:
        raise ValueError("polygon contains no grid point")
    return best


def room_goals(rooms):
    """{room id: (x, y, clearance)} for layout or scene-graph room dicts with 'id' and 'polygon'."""
    return {r["id"]: room_goal(r["polygon"]) for r in rooms}
