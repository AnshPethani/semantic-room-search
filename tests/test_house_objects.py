"""ROS-free tests for target objects (D-070 to D-073): catalog, demo scenario, placement rules."""
import copy
import importlib.util
import re
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

COCO = {
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
}
# Ansh's detector vocabulary (12 COCO classes, 2026-11-14). The world must be able to contain
# every class the LLM may name. To be replaced by reading his vocabulary file after the pull.
VOCABULARY = {"banana", "apple", "orange", "sandwich", "bottle", "cup", "bowl", "book", "laptop",
              "remote", "cell phone", "teddy bear"}


@pytest.fixture(scope="module")
def layout():
    return gen.load_layout(PKG / "layout" / "house_layout.yaml")


@pytest.fixture(scope="module")
def catalog():
    return ho.load_yaml(PKG / "objects" / "catalog.yaml")


@pytest.fixture(scope="module")
def demo():
    return ho.load_yaml(PKG / "objects" / "scenarios" / "demo.yaml")


@pytest.fixture(scope="module")
def placed(layout, catalog, demo):
    return ho.place_objects(layout, catalog, demo)


# ----------------------------------------------------------------- catalog
def test_catalog_classes_are_the_detector_vocabulary(catalog):
    assert set(catalog["classes"]) == VOCABULARY
    assert set(catalog["classes"]) <= COCO


def test_catalog_sizes_are_plausible(catalog):
    for label, spec in catalog["classes"].items():
        assert 0.01 <= ho.height(spec) <= 0.4, label
        assert 0.01 <= ho.footprint_radius(spec) <= 0.25, label


# ----------------------------------------------------------------- demo scenario
def test_demo_places_one_object_of_every_class(placed, catalog):
    assert sorted(o["label"] for o in placed) == sorted(catalog["classes"])


def test_demo_objects_are_in_their_declared_rooms(placed, layout):
    rooms = {r["id"]: r["polygon"] for r in layout["rooms"]}
    for o in placed:
        inside = [rid for rid, poly in rooms.items() if gen.point_in_polygon((o["x"], o["y"]), poly)]
        assert inside == [o["room"]], o["name"]


def test_model_names_are_unique_and_map_back_to_labels(placed):
    names = [o["name"] for o in placed]
    assert len(set(names)) == len(names)
    for o in placed:
        assert re.fullmatch(r"obj_[a-z]+(_[a-z]+)*_\d+", o["name"]), o["name"]
        assert ho.label_from_model_name(o["name"]) == o["label"]


def test_objects_rest_on_the_floor(placed, catalog):
    for o in placed:
        assert o["z"] == pytest.approx(ho.height(catalog["classes"][o["label"]]) / 2)


def test_object_sdf_is_a_static_model_with_one_collision(placed, catalog):
    for o in placed:
        model = ET.fromstring(o["sdf"]).find("model")
        assert model.get("name") == o["name"]
        assert model.find("static").text == "true"
        link = model.find("link")
        assert len(link.findall("collision")) == 1 and len(link.findall("visual")) == 1
        shape = catalog["classes"][o["label"]]["shape"]
        assert link.find(f"collision/geometry/{shape}") is not None, o["name"]


# ----------------------------------------------------------------- truth files (D-074)
TRUTH_DEMO = REPO / "data" / "objects_demo.json"


def test_truth_file_matches_the_scenario(placed, catalog):
    t = ho.truth("demo", placed, catalog)
    assert (t["scenario"], t["frame"], t["units"]) == ("demo", "map", "m")
    assert [o["name"] for o in t["objects"]] == [o["name"] for o in placed]
    for entry, o in zip(t["objects"], placed):
        assert entry["label"] == o["label"] == ho.label_from_model_name(entry["name"])
        assert entry["position"] == [o["x"], o["y"], o["z"]]
        assert entry["height"] == pytest.approx(2 * o["z"])


def test_committed_truth_file_is_current(placed, catalog):
    assert TRUTH_DEMO.exists(), "run: python ros/house_sim/scripts/house_objects.py"
    committed = TRUTH_DEMO.read_bytes().replace(b"\r\n", b"\n")
    assert committed == ho.dump_truth(ho.truth("demo", placed, catalog)).encode(), \
        "data/objects_demo.json is stale; run: python ros/house_sim/scripts/house_objects.py"


# ----------------------------------------------------------------- placement rules
def _with(demo, index, **changes):
    s = copy.deepcopy(demo)
    s["objects"][index].update(changes)
    return s


def test_rejects_unknown_class(layout, catalog, demo):
    with pytest.raises(ho.ObjectError, match="unknown class"):
        ho.place_objects(layout, catalog, _with(demo, 0, label="giraffe"))


def test_rejects_wrong_room(layout, catalog, demo):
    with pytest.raises(ho.ObjectError, match="not inside room"):
        ho.place_objects(layout, catalog, _with(demo, 0, room="D"))


def test_rejects_object_against_a_wall(layout, catalog, demo):
    with pytest.raises(ho.ObjectError, match="from walls"):
        ho.place_objects(layout, catalog, _with(demo, 0, xy=[0.2, 0.6]))


def test_rejects_object_in_a_doorway(layout, catalog, demo):
    # Just inside K below the E-K door gap (1.2..2.2 on y = 4.1).
    with pytest.raises(ho.ObjectError, match="from door gaps"):
        ho.place_objects(layout, catalog, _with(demo, 0, xy=[1.7, 3.7]))


def test_rejects_object_on_a_room_goal(layout, catalog, demo):
    with pytest.raises(ho.ObjectError, match="from room goals"):
        ho.place_objects(layout, catalog, _with(demo, 0, xy=[2.5, 2.0]))


def test_rejects_objects_too_close_together(layout, catalog, demo):
    with pytest.raises(ho.ObjectError, match="from obj_banana_0"):
        ho.place_objects(layout, catalog, _with(demo, 1, xy=[0.6, 1.0]))


def test_rejects_unknown_shape(layout, demo, catalog):
    bad = copy.deepcopy(catalog)
    bad["classes"]["banana"] = {"shape": "cone", "radius": 0.1, "color": [1, 1, 0]}
    with pytest.raises(ho.ObjectError, match="unknown shape"):
        ho.place_objects(layout, bad, demo)
