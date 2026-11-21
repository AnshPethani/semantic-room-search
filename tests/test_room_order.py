"""ROS-free tests for the room-order planner and the E2 baselines (D-140 to D-144)."""
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "ros" / "house_sim" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ro = _load("room_order")
P = ro.PlannerParams()


@pytest.fixture(scope="module")
def rooms():
    return json.loads((REPO / "data" / "scene_graph.json").read_text(encoding="utf-8"))["rooms"]


@pytest.fixture(scope="module")
def start():
    layout = yaml.safe_load((REPO / "ros" / "house_sim" / "layout" / "house_layout.yaml")
                            .read_text(encoding="utf-8"))
    s = layout["robot_start"]
    return (s["x"], s["y"])


def _room(rid, n_vp=1, xy=(0.0, 0.0)):
    return {"id": rid, "viewpoints": [list(xy)] * n_vp}


# ----------------------------------------------------------------------------- priors

def test_uniform_prior():
    p = ro.uniform_prior(["A", "B", "C", "D"])
    assert p == {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    with pytest.raises(ValueError):
        ro.uniform_prior([])


def test_planner_prior_failure_is_uniform():
    # D-008: success false -> uniform prior, every room still searched
    assert ro.planner_prior(False, None, ["A", "B"]) == {"A": 0.5, "B": 0.5}
    assert ro.planner_prior(False, {"A": 0.9, "B": 0.1}, ["A", "B"]) == {"A": 0.5, "B": 0.5}


def test_planner_prior_success_is_used_and_renormalized():
    # D-008: llm, cache and fallback priors are used alike
    assert ro.planner_prior(True, {"A": 0.6, "B": 0.4}, ["A", "B"]) == {"A": 0.6, "B": 0.4}
    p = ro.planner_prior(True, {"A": 3.0, "B": 1.0}, ["A", "B"])
    assert p["A"] == pytest.approx(0.75) and p["B"] == pytest.approx(0.25)


@pytest.mark.parametrize("bad", [None, {"A": 1.0}, {"A": 0.5, "B": 0.5, "C": 0.0},
                                 {"A": -0.1, "B": 1.1}, {"A": 0.0, "B": 0.0},
                                 {"A": math.nan, "B": 1.0}])
def test_planner_prior_rejects_bad_priors(bad):
    with pytest.raises(ValueError):
        ro.planner_prior(True, bad, ["A", "B"])


# ------------------------------------------------------------------------------ costs

def test_params_validation():
    with pytest.raises(ValueError):
        ro.PlannerParams(search_cost_per_viewpoint=0.0)


def test_search_cost_grows_with_viewpoints():
    assert ro.search_cost(_room("A", 1), P) == pytest.approx(P.search_cost_per_viewpoint)
    assert ro.search_cost(_room("A", 3), P) == pytest.approx(3 * P.search_cost_per_viewpoint)


def test_ratio_formula():
    assert ro.ratio(0.5, 3.0, 2.0) == pytest.approx(0.1)
    assert ro.ratio(0.5, math.inf, 2.0) == 0.0


def test_straight_line_travel_uses_nearest_viewpoint():
    rooms = [{"id": "A", "viewpoints": [[3.0, 4.0], [1.0, 0.0]]}]
    assert ro.straight_line_travel((0.0, 0.0), rooms) == {"A": pytest.approx(1.0)}


def test_viewpoint_order_is_shortest_open_path():
    vps = [(10.0, 0.0), (1.0, 0.0), (5.0, 0.0)]
    assert ro.viewpoint_order((0.0, 0.0), vps) == [(1.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
    assert ro.viewpoint_order((11.0, 0.0), vps) == [(10.0, 0.0), (5.0, 0.0), (1.0, 0.0)]
    assert ro.viewpoint_order((0.0, 0.0), [(2.0, 2.0)]) == [(2.0, 2.0)]
    with pytest.raises(ValueError):
        ro.viewpoint_order((0.0, 0.0), [])


# ------------------------------------------------------------------------- next room

ROOMS3 = [_room("A"), _room("B"), _room("C")]


def test_ours_picks_most_likely_room_when_costs_are_equal():
    travel = {"A": 4.0, "B": 4.0, "C": 4.0}
    prior = {"A": 0.2, "B": 0.7, "C": 0.1}
    assert ro.next_room("ours", ROOMS3, [], travel, prior) == "B"


def test_ours_trades_probability_against_cost():
    # A is a bit more likely but far away; B is close: 0.40/22.5 < 0.35/4.5
    travel = {"A": 20.0, "B": 2.0, "C": 3.0}
    prior = {"A": 0.40, "B": 0.35, "C": 0.25}
    assert ro.next_room("ours", ROOMS3, [], travel, prior) == "B"


def test_ours_counts_search_cost():
    # same prior and travel; A needs three viewpoints, B one
    rooms = [_room("A", 3), _room("B", 1)]
    travel = {"A": 1.0, "B": 1.0}
    assert ro.next_room("ours", rooms, [], travel, {"A": 0.5, "B": 0.5}) == "B"


def test_ours_zero_probability_rooms_come_last():
    travel = {"A": 0.1, "B": 50.0, "C": 60.0}
    prior = {"A": 0.0, "B": 0.5, "C": 0.5}
    order, visited = [], []
    while (r := ro.next_room("ours", ROOMS3, visited, travel, prior)) is not None:
        order.append(r)
        visited.append(r)
    assert order == ["B", "C", "A"]


def test_ties_are_broken_by_travel_then_id():
    prior = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
    assert ro.next_room("ours", ROOMS3, [], {"A": 1.0, "B": 1.0, "C": 1.0}, prior) == "A"
    assert ro.next_room("nearest", ROOMS3, [], {"A": 2.0, "B": 1.0, "C": 1.0}) == "B"


def test_visited_rooms_are_skipped_and_none_when_done():
    travel = {"A": 1.0, "B": 2.0, "C": 3.0}
    assert ro.next_room("nearest", ROOMS3, ["A"], travel) == "B"
    for s in ro.STRATEGIES:
        assert ro.next_room(s, ROOMS3, ["A", "B", "C"], travel, ro.uniform_prior("ABC"),
                            "A", ro.PlannerParams(sweep_order=("A", "B", "C"))) is None


def test_unreachable_room_goes_last():
    travel = {"A": math.inf, "B": 5.0, "C": 9.0}
    prior = {"A": 0.8, "B": 0.1, "C": 0.1}
    assert ro.next_room("ours", ROOMS3, [], travel, prior) == "B"
    assert ro.next_room("nearest", ROOMS3, ["B", "C"], travel) == "A"


def test_nearest():
    assert ro.next_room("nearest", ROOMS3, [], {"A": 3.0, "B": 1.0, "C": 2.0}) == "B"


def test_sweep_follows_fixed_order():
    params = ro.PlannerParams(sweep_order=("C", "A", "B"))
    assert ro.next_room("sweep", ROOMS3, [], params=params) == "C"
    assert ro.next_room("sweep", ROOMS3, ["C"], params=params) == "A"
    assert ro.next_room("sweep", ROOMS3, ["C", "B"], params=params) == "A"
    with pytest.raises(ValueError):
        ro.next_room("sweep", ROOMS3, [], params=ro.PlannerParams(sweep_order=("A", "B")))


def test_oracle_goes_to_true_room_then_nearest():
    travel = {"A": 1.0, "B": 2.0, "C": 9.0}
    assert ro.next_room("oracle", ROOMS3, [], travel, true_room="C") == "C"
    assert ro.next_room("oracle", ROOMS3, ["C"], travel, true_room="C") == "A"
    with pytest.raises(ValueError):
        ro.next_room("oracle", ROOMS3, [], travel)


def test_bad_inputs():
    with pytest.raises(ValueError):
        ro.next_room("random", ROOMS3, [], {"A": 1, "B": 1, "C": 1})
    with pytest.raises(ValueError):
        ro.next_room("nearest", ROOMS3, ["X"], {"A": 1, "B": 1, "C": 1})
    with pytest.raises(ValueError):
        ro.next_room("nearest", ROOMS3, [], {"A": 1})
    with pytest.raises(ValueError):
        ro.next_room("ours", ROOMS3, [], {"A": 1, "B": 1, "C": 1})


# ------------------------------------------------------------------- real scene graph

def test_default_sweep_order_matches_the_house(rooms):
    assert sorted(P.sweep_order) == sorted(r["id"] for r in rooms)


@pytest.mark.parametrize("strategy", ro.STRATEGIES)
def test_every_strategy_searches_every_room_once(rooms, start, strategy):
    # completeness (proposal): if the target is not found, every room is still searched
    order = ro.full_order(strategy, rooms, start, prior=ro.uniform_prior(r["id"] for r in rooms),
                          true_room="B2")
    assert sorted(order) == sorted(r["id"] for r in rooms)


def test_food_command_searches_kitchen_first(rooms, start):
    # the proposal's example prior for "find me food"
    prior = {"K": 0.55, "D": 0.30, "LR": 0.10, "E": 0.02, "B1": 0.015, "B2": 0.015}
    order = ro.full_order("ours", rooms, start, prior=prior)
    assert order[0] == "K"
    assert order.index("D") < order.index("B1")


def test_nearest_first_starts_in_the_entry_hall(rooms, start):
    assert ro.full_order("nearest", rooms, start)[0] == "E"


def test_oracle_starts_in_true_room(rooms, start):
    assert ro.full_order("oracle", rooms, start, true_room="B2")[0] == "B2"
