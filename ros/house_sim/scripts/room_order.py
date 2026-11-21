"""Room-order planner and the E2 baselines (D-140 to D-144).

ROS-free (standard library only), so it is tested with plain pytest. The task manager calls
next_room() once per room: travel costs depend on where the robot is, so the choice is made
greedily, one room at a time, after each room is searched (proposal, Step 2).

Strategies (proposal, E2):
  ours     r* = argmax over unvisited r of  P(r | u) / (c_travel(r) + c_search(r))
  nearest  smallest c_travel first (nearest-room-first)
  sweep    a fixed room order, the same for every trial
  oracle   the room that really holds the target first (upper bound), then nearest-first

Costs are in meters (D-141): c_travel is the path length from the robot to the room's nearest
viewpoint (Nav2 in the task manager, straight lines in offline tests); c_search is a fixed
meter-equivalent per viewpoint, because every viewpoint costs one 360 degree turn.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

STRATEGIES = ("ours", "nearest", "sweep", "oracle")

Point = tuple[float, float]
TravelFn = Callable[[Point, Sequence[Mapping]], dict[str, float]]


@dataclass(frozen=True)
class PlannerParams:
    # m per viewpoint: meter-equivalent of one 360 deg turn plus the short moves around it
    # (D-141). A first guess, to be replaced by the measured turn time x the mean speed.
    search_cost_per_viewpoint: float = 2.5
    # Fixed-sweep baseline order (D-143): follows the doors from the start in E.
    sweep_order: tuple[str, ...] = ("E", "K", "LR", "D", "B2", "B1")

    def __post_init__(self):
        if not self.search_cost_per_viewpoint > 0:
            raise ValueError("search_cost_per_viewpoint must be > 0")


DEFAULT_PARAMS = PlannerParams()


# ------------------------------------------------------------------------------- priors

def uniform_prior(room_ids: Iterable[str]) -> dict[str, float]:
    ids = list(room_ids)
    if not ids:
        raise ValueError("no rooms")
    return {r: 1.0 / len(ids) for r in ids}


def planner_prior(success: bool, room_prior: Mapping[str, float] | None,
                  room_ids: Sequence[str]) -> dict[str, float]:
    """The prior the planner uses for one /ground_command answer (D-008).

    success False (no prior): uniform, so the cost term alone orders the rooms.
    success True (source llm, cache or fallback alike): the returned prior, renormalized.
    """
    if not success:
        return uniform_prior(room_ids)
    if room_prior is None or set(room_prior) != set(room_ids):
        raise ValueError(f"room_prior must have exactly the rooms {sorted(room_ids)}")
    if any(p < 0 or not math.isfinite(p) for p in room_prior.values()):
        raise ValueError("room_prior has a negative or non-finite value")
    total = sum(room_prior.values())
    if total <= 0:
        raise ValueError("room_prior sums to 0")
    return {r: room_prior[r] / total for r in room_ids}


# -------------------------------------------------------------------------------- costs

def search_cost(room: Mapping, params: PlannerParams) -> float:
    """c_search(r): grows with the number of viewpoints (D-141)."""
    return params.search_cost_per_viewpoint * len(room["viewpoints"])


def ratio(prob: float, travel: float, search: float) -> float:
    """P(r | u) / (c_travel + c_search); an unreachable room (infinite travel) scores 0."""
    return prob / (travel + search)


def viewpoint_order(start: Point, viewpoints: Sequence[Point]) -> list[Point]:
    """Visiting order inside a room: the shortest open path from start (D-144).

    Rooms have 1-3 viewpoints (D-080), so trying every order is at most 6 paths.
    """
    if not viewpoints:
        raise ValueError("room has no viewpoints")
    best, best_len = None, math.inf
    for perm in itertools.permutations(viewpoints):
        length, here = 0.0, start
        for p in perm:
            length += math.dist(here, p)
            here = p
        if length < best_len - 1e-12:
            best, best_len = perm, length
    return [tuple(p) for p in best]


def straight_line_travel(pose: Point, rooms: Sequence[Mapping]) -> dict[str, float]:
    """c_travel for offline use: straight line to the room's nearest viewpoint (ignores walls)."""
    return {r["id"]: min(math.dist(pose, v) for v in r["viewpoints"]) for r in rooms}


# ---------------------------------------------------------------------------- next room

def next_room(strategy: str, rooms: Sequence[Mapping], visited: Iterable[str],
              travel: Mapping[str, float] | None = None,
              prior: Mapping[str, float] | None = None,
              true_room: str | None = None,
              params: PlannerParams = DEFAULT_PARAMS) -> str | None:
    """The next room to search, or None once every room has been visited.

    rooms: scene-graph rooms (id, viewpoints). visited: rooms already searched or skipped.
    travel: c_travel per unvisited room from the robot's current pose (not needed for sweep).
    prior: P(r | u) (ours only). true_room: the room that holds the target (oracle only).
    Ties are broken by smaller travel, then by room id, so the choice is deterministic (D-142).
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; expected one of {STRATEGIES}")
    ids = [r["id"] for r in rooms]
    done = set(visited)
    unknown = done - set(ids)
    if unknown:
        raise ValueError(f"visited has unknown rooms {sorted(unknown)}")
    todo = [r for r in rooms if r["id"] not in done]
    if not todo:
        return None

    if strategy == "sweep":
        if sorted(params.sweep_order) != sorted(ids):
            raise ValueError(f"sweep_order {params.sweep_order} must list each room once")
        return next(r for r in params.sweep_order if r not in done)

    if travel is None or any(r["id"] not in travel for r in todo):
        raise ValueError(f"{strategy} needs travel costs for every unvisited room")

    def nearest_key(r):
        return (travel[r["id"]], r["id"])

    if strategy == "nearest":
        return min(todo, key=nearest_key)["id"]

    if strategy == "oracle":
        if true_room not in ids:
            raise ValueError(f"oracle needs true_room, one of {ids}")
        if true_room not in done:
            return true_room
        return min(todo, key=nearest_key)["id"]

    # ours
    if prior is None or any(r["id"] not in prior for r in todo):
        raise ValueError("ours needs a prior for every unvisited room")
    return min(todo, key=lambda r: (-ratio(prior[r["id"]], travel[r["id"]],
                                           search_cost(r, params)),) + nearest_key(r))["id"]


def full_order(strategy: str, rooms: Sequence[Mapping], start: Point,
               travel_fn: TravelFn = straight_line_travel,
               prior: Mapping[str, float] | None = None, true_room: str | None = None,
               params: PlannerParams = DEFAULT_PARAMS) -> list[str]:
    """The whole room order if the target is never found (offline checks and examples).

    After each room the robot is assumed to stand at the last viewpoint it visited there.
    """
    by_id = {r["id"]: r for r in rooms}
    order, pose = [], start
    while True:
        travel = travel_fn(pose, [by_id[i] for i in by_id if i not in order])
        room = next_room(strategy, rooms, order, travel, prior, true_room, params)
        if room is None:
            return order
        order.append(room)
        pose = viewpoint_order(pose, [tuple(v) for v in by_id[room]["viewpoints"]])[-1]
