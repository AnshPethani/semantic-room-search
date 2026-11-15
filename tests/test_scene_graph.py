import json
from pathlib import Path

import pytest

from lang_grounding.scene_graph import (
    SceneGraph,
    SceneGraphError,
    load_scene_graph,
    main,
    parse_scene_graph,
    render_for_prompt,
)

DATA = Path(__file__).resolve().parents[1] / "data"
PLACEHOLDER = DATA / "scene_graph.placeholder.json"
SCHEMA = DATA / "scene_graph.schema.json"


@pytest.fixture
def raw():
    """Fresh mutable copy of the placeholder JSON."""
    return json.loads(PLACEHOLDER.read_text())


def _room(d, rid):
    return next(r for r in d["rooms"] if r["id"] == rid)


def _door(d, did):
    return next(x for x in d["doors"] if x["id"] == did)


# ----------------------------------------------------------------- positive

def test_placeholder_validates():
    g = load_scene_graph(PLACEHOLDER)
    assert g.room_ids == ["E", "K", "LR", "D", "B1", "B2"]
    assert len(g.doors) == 7


def test_neighbors_match_d002():
    g = load_scene_graph(PLACEHOLDER)
    assert {k: set(v) for k, v in g.neighbors.items()} == {
        "E": {"K", "LR"},
        "K": {"E", "LR"},
        "LR": {"E", "K", "B1", "B2", "D"},
        "D": {"LR"},
        "B1": {"LR"},
        "B2": {"LR"},
    }


def test_k_and_d_are_not_neighbors():
    g = load_scene_graph(PLACEHOLDER)
    assert "D" not in g.neighbors["K"]
    assert "K" not in g.neighbors["D"]


def test_outside_excluded_from_neighbors():
    g = load_scene_graph(PLACEHOLDER)
    assert all("outside" not in ns for ns in g.neighbors.values())
    assert g.exterior_rooms == ("E",)


def test_neighbors_not_stored_in_json(raw):
    assert "neighbors" not in raw
    assert all("neighbors" not in r for r in raw["rooms"])


def test_lr_is_non_convex_and_accepted():
    g = load_scene_graph(PLACEHOLDER)
    assert len(g.room("LR").polygon) == 6


def test_area_and_centroid_within_tolerance_pass(raw):
    _room(raw, "K")["area"] += 0.04
    _room(raw, "K")["centroid"][0] += 0.04
    parse_scene_graph(raw)


# ----------------------------------------------------------------- negative: top level

def test_unsupported_schema_version(raw):
    raw["schema_version"] = 2
    with pytest.raises(SceneGraphError, match="schema_version"):
        parse_scene_graph(raw)


def test_missing_field(raw):
    del raw["rooms"][0]["name"]
    with pytest.raises(SceneGraphError, match="rooms.0.name"):
        parse_scene_graph(raw)


def test_wrong_frame(raw):
    raw["frame"] = "odom"
    with pytest.raises(SceneGraphError, match="frame"):
        parse_scene_graph(raw)


def test_not_an_object():
    with pytest.raises(SceneGraphError):
        parse_scene_graph([])


# ----------------------------------------------------------------- negative: rooms

def test_duplicate_room_id(raw):
    raw["rooms"][1]["id"] = "E"
    with pytest.raises(SceneGraphError, match="duplicate room ID 'E'"):
        parse_scene_graph(raw)


def test_outside_is_reserved(raw):
    _room(raw, "D")["id"] = "outside"
    with pytest.raises(SceneGraphError, match="reserved"):
        parse_scene_graph(raw)


def test_polygon_too_few_vertices(raw):
    _room(raw, "E")["polygon"] = [[0.0, 4.1], [3.3, 4.1]]
    with pytest.raises(SceneGraphError, match="room 'E'.*at least 3 vertices"):
        parse_scene_graph(raw)


def test_clockwise_polygon(raw):
    _room(raw, "E")["polygon"].reverse()
    with pytest.raises(SceneGraphError, match="room 'E'.*clockwise"):
        parse_scene_graph(raw)


def test_clockwise_nonconvex_polygon(raw):
    _room(raw, "LR")["polygon"].reverse()
    with pytest.raises(SceneGraphError, match="room 'LR'.*clockwise"):
        parse_scene_graph(raw)


def test_self_intersecting_polygon(raw):
    _room(raw, "E")["polygon"] = [[0.0, 4.1], [3.3, 9.0], [3.3, 4.1], [0.0, 9.0]]
    with pytest.raises(SceneGraphError, match="room 'E'.*self-intersects"):
        parse_scene_graph(raw)


def test_polygon_doubling_back(raw):
    _room(raw, "E")["polygon"] = [[0.0, 4.1], [3.3, 4.1], [1.0, 4.1], [3.3, 9.0], [0.0, 9.0]]
    with pytest.raises(SceneGraphError, match="room 'E'.*self-intersects"):
        parse_scene_graph(raw)


def test_repeated_vertex(raw):
    _room(raw, "E")["polygon"].insert(1, [0.0, 4.1])
    with pytest.raises(SceneGraphError, match="room 'E'.*repeated"):
        parse_scene_graph(raw)


def test_collinear_polygon_rejected(raw):
    # A degenerate (zero-area) polygon always has overlapping edges, so the
    # self-intersection check reports it before the zero-area backstop is reached.
    _room(raw, "E")["polygon"] = [[0.0, 4.1], [1.0, 4.1], [2.0, 4.1]]
    with pytest.raises(SceneGraphError, match="room 'E'.*self-intersects"):
        parse_scene_graph(raw)


def test_area_mismatch(raw):
    _room(raw, "K")["area"] = 25.0
    with pytest.raises(SceneGraphError, match="room 'K'.*area"):
        parse_scene_graph(raw)


def test_centroid_mismatch(raw):
    _room(raw, "LR")["centroid"] = [5.0, 4.0]
    with pytest.raises(SceneGraphError, match="room 'LR'.*centroid"):
        parse_scene_graph(raw)


# ----------------------------------------------------------------- negative: doors

def test_duplicate_door_id(raw):
    raw["doors"][1]["id"] = raw["doors"][0]["id"]
    with pytest.raises(SceneGraphError, match="duplicate door ID 'd_E_out'"):
        parse_scene_graph(raw)


def test_door_unknown_room(raw):
    _door(raw, "d_K_LR")["between"] = ["K", "ZZ"]
    with pytest.raises(SceneGraphError, match="door 'd_K_LR'.*unknown room 'ZZ'"):
        parse_scene_graph(raw)


def test_door_same_room_twice(raw):
    _door(raw, "d_K_LR")["between"] = ["K", "K"]
    with pytest.raises(SceneGraphError, match="door 'd_K_LR'.*itself"):
        parse_scene_graph(raw)


def test_door_wrong_arity(raw):
    _door(raw, "d_K_LR")["between"] = ["K", "LR", "E"]
    with pytest.raises(SceneGraphError, match="door 'd_K_LR'.*exactly 2"):
        parse_scene_graph(raw)


def test_door_off_boundary(raw):
    _door(raw, "d_K_LR")["position"] = [5.5, 2.8]
    with pytest.raises(SceneGraphError, match="door 'd_K_LR'.*boundary"):
        parse_scene_graph(raw)


def test_door_on_one_room_boundary_only(raw):
    # (4.5, 4.1) is on K's top edge but not on E's boundary.
    _door(raw, "d_E_K")["position"] = [4.5, 4.1]
    with pytest.raises(SceneGraphError, match="door 'd_E_K'.*room 'E'"):
        parse_scene_graph(raw)


def test_exterior_door_off_boundary(raw):
    _door(raw, "d_E_out")["position"] = [1.8, 8.0]
    with pytest.raises(SceneGraphError, match="door 'd_E_out'.*room 'E'"):
        parse_scene_graph(raw)


# ----------------------------------------------------------------- file loading

def test_missing_file(tmp_path):
    with pytest.raises(SceneGraphError, match="cannot read"):
        load_scene_graph(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(SceneGraphError, match="not valid JSON"):
        load_scene_graph(p)


# ----------------------------------------------------------------- prompt text

def test_render_for_prompt():
    g = load_scene_graph(PLACEHOLDER)
    text = render_for_prompt(g)
    assert "connected by a door" in text
    assert "share a wall" in text
    for r in g.rooms:
        assert f"- {r.id}: {r.name}" in text
    k_line = next(line for line in text.splitlines() if line.startswith("- K:"))
    assert "E (entry hall)" in k_line and "LR (living room)" in k_line
    assert "D (dining area)" not in k_line
    assert "outside" in next(line for line in text.splitlines() if line.startswith("- E:"))
    assert "outside" not in k_line


# ----------------------------------------------------------------- CLI

def test_cli_ok(capsys):
    assert main(["validate", str(PLACEHOLDER)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK:")
    assert "6 rooms, 7 doors" in out


def test_cli_error(tmp_path, raw, capsys):
    _room(raw, "K")["area"] = 99.0
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    assert main(["validate", str(p)]) == 1
    assert "ERROR: room 'K'" in capsys.readouterr().err


def test_cli_missing_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.json")]) == 1
    assert "ERROR:" in capsys.readouterr().err


# ----------------------------------------------------------------- schema file

def test_schema_file_matches_models():
    schema = json.loads(SCHEMA.read_text())
    model = SceneGraph.model_json_schema()
    assert set(schema["required"]) == set(model["required"])
    assert set(schema["properties"]) == set(model["properties"])
    for name in ("Room", "Door"):
        assert set(schema["$defs"][name]["required"]) == set(model["$defs"][name]["required"])
        assert set(schema["$defs"][name]["properties"]) == set(
            model["$defs"][name]["properties"]
        )


def test_placeholder_has_only_schema_keys():
    schema = json.loads(SCHEMA.read_text())
    raw = json.loads(PLACEHOLDER.read_text())
    assert set(raw) == set(schema["properties"])
    room_schema = schema["$defs"]["Room"]
    for r in raw["rooms"]:
        # viewpoints is optional, so a room may omit it
        assert set(room_schema["required"]) <= set(r) <= set(room_schema["properties"])
    for d in raw["doors"]:
        assert set(d) == set(schema["$defs"]["Door"]["properties"])


# ----------------------------------------------------------------- viewpoints (D-047)

def test_viewpoints_optional_in_schema():
    room_schema = json.loads(SCHEMA.read_text())["$defs"]["Room"]
    assert "viewpoints" in room_schema["properties"]
    assert "viewpoints" not in room_schema["required"]


def test_viewpoints_default_to_none():
    g = load_scene_graph(PLACEHOLDER)
    assert all(r.viewpoints is None for r in g.rooms)


def test_valid_viewpoints_are_loaded(raw):
    _room(raw, "E")["viewpoints"] = [[1.65, 6.55]]
    _room(raw, "LR")["viewpoints"] = [[4.0, 5.0], [6.0, 3.0]]  # LR arm and main part
    g = parse_scene_graph(raw)
    assert g.room("E").viewpoints == [(1.65, 6.55)]
    assert len(g.room("LR").viewpoints) == 2


def test_empty_viewpoints_list_accepted(raw):
    _room(raw, "E")["viewpoints"] = []
    assert parse_scene_graph(raw).room("E").viewpoints == []


def test_viewpoint_outside_room(raw):
    _room(raw, "E")["viewpoints"] = [[1.65, 6.55], [5.0, 6.0]]
    with pytest.raises(SceneGraphError, match=r"room 'E': viewpoint 1 \[5.0, 6.0\] is outside"):
        parse_scene_graph(raw)


def test_viewpoint_in_lr_notch_rejected(raw):
    # (4.0, 2.5) is inside LR's bounding box but in the notch cut out by K.
    _room(raw, "LR")["viewpoints"] = [[4.0, 2.5]]
    with pytest.raises(SceneGraphError, match="room 'LR': viewpoint 0.*outside"):
        parse_scene_graph(raw)


def test_same_point_is_valid_in_the_room_that_owns_the_notch(raw):
    _room(raw, "K")["viewpoints"] = [[4.0, 2.5]]
    parse_scene_graph(raw)


def test_viewpoint_on_boundary_and_within_tolerance(raw):
    # LR's notch edge is x = 5.1 for y in [1.5, 4.1].
    _room(raw, "LR")["viewpoints"] = [[5.1, 2.8], [5.06, 2.8]]
    parse_scene_graph(raw)


def test_viewpoint_beyond_tolerance_rejected(raw):
    _room(raw, "LR")["viewpoints"] = [[4.9, 2.8]]  # 0.2 m into the notch
    with pytest.raises(SceneGraphError, match="room 'LR': viewpoint 0"):
        parse_scene_graph(raw)


def test_viewpoint_wrong_shape(raw):
    _room(raw, "E")["viewpoints"] = [[1.0, 5.0, 2.0]]
    with pytest.raises(SceneGraphError, match="viewpoints"):
        parse_scene_graph(raw)


def test_viewpoints_not_in_prompt_text(raw):
    _room(raw, "E")["viewpoints"] = [[1.65, 6.55]]
    text = render_for_prompt(parse_scene_graph(raw))
    assert "viewpoint" not in text.lower()
    assert "1.65" not in text


def test_generated_scene_graph_with_viewpoints_validates():
    g = load_scene_graph(DATA / "scene_graph.json")
    assert all(r.viewpoints for r in g.rooms)
