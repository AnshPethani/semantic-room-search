import csv
from pathlib import Path

import pytest

from lang_grounding.config import load_config
from lang_grounding.e1_labels import (
    LabelsError,
    compare_labels,
    format_comparison,
    load_e1_commands,
    main,
    validate_labels,
)
from lang_grounding.scene_graph import load_scene_graph

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = load_config()
GRAPH = load_scene_graph(CONFIG.resolve(CONFIG.paths.scene_graph))
ROOMS = GRAPH.room_ids
COMMANDS = load_e1_commands(DATA / "e1_commands.json")
BY_ID = {c.id: c for c in COMMANDS}
HEADER = ["id", "command", *ROOMS, "notes"]


def default_labels():
    """A valid labeling: the first allowed room for constrained commands, else K."""
    return {c.id: {c.expected_constraint[0]} if c.expected_constraint else {"K"}
            for c in COMMANDS}


def rows_for(labels):
    rows = []
    for c in COMMANDS:
        row = {"id": c.id, "command": c.command, "notes": ""}
        row.update({r: "1" if r in labels[c.id] else "" for r in ROOMS})
        rows.append(row)
    return rows


def write_rows(tmp_path, rows, *, name="labels.csv", header=HEADER):
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_labels(tmp_path, labels, **kwargs):
    return write_rows(tmp_path, rows_for(labels), **kwargs)


def check(path):
    return validate_labels(path, COMMANDS, ROOMS)


def has(messages, *fragments):
    return any(all(f in m for f in fragments) for m in messages)


# ----------------------------------------------------------------- valid

def test_valid_file(tmp_path):
    report = check(write_labels(tmp_path, default_labels()))
    assert report.errors == [] and report.warnings == []
    assert report.ok
    assert set(report.labels) == set(BY_ID)
    assert report.labels["e1_01"] == frozenset({"K"})
    assert report.labels["e1_28"] == frozenset({"E"})  # first allowed room


def test_notes_column_is_optional(tmp_path):
    header = [h for h in HEADER if h != "notes"]
    assert check(write_labels(tmp_path, default_labels(), header=header)).ok


def test_room_column_order_does_not_matter_and_bom_is_fine(tmp_path):
    header = ["notes", *reversed(ROOMS), "command", "id"]
    path = write_labels(tmp_path, default_labels(), header=header)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert check(path).ok


def test_whitespace_in_cells_and_commands_is_tolerated(tmp_path):
    rows = rows_for(default_labels())
    rows[0]["K"] = " 1 "
    rows[1]["command"] = "  " + rows[1]["command"] + "  "
    assert check(write_rows(tmp_path, rows)).ok


def test_real_commands_load():
    assert len(COMMANDS) > 0
    assert BY_ID["e1_28"].expected_constraint == ("E", "LR")
    assert BY_ID["e1_01"].expected_constraint is None


# ----------------------------------------------------------------- ids and rows

def test_wrong_id(tmp_path):
    rows = rows_for(default_labels())
    rows[4]["id"] = "e1_99"
    errors = check(write_rows(tmp_path, rows)).errors
    assert has(errors, "unknown id 'e1_99'")
    assert has(errors, "missing row for e1_05")


def test_missing_row(tmp_path):
    rows = [r for r in rows_for(default_labels()) if r["id"] != "e1_07"]
    errors = check(write_rows(tmp_path, rows)).errors
    assert errors == [f"{tmp_path / 'labels.csv'}: missing row for e1_07 "
                      f"({BY_ID['e1_07'].command!r})"]


def test_duplicate_row(tmp_path):
    rows = rows_for(default_labels())
    rows.append(dict(rows[2]))
    assert has(check(write_rows(tmp_path, rows)).errors, "duplicate row for e1_03")


def test_blank_id(tmp_path):
    rows = rows_for(default_labels())
    rows[0]["id"] = ""
    errors = check(write_rows(tmp_path, rows)).errors
    assert has(errors, "row has no id") and has(errors, "missing row for e1_01")


def test_command_text_must_match(tmp_path):
    rows = rows_for(default_labels())
    rows[0]["command"] = "find the apple"
    assert has(check(write_rows(tmp_path, rows)).errors, "e1_01", "does not match")


# ----------------------------------------------------------------- cells

@pytest.mark.parametrize("value", ["0", "x", "2", "yes", "1.0"])
def test_bad_cell_value(tmp_path, value):
    rows = rows_for(default_labels())
    rows[0]["D"] = value
    errors = check(write_rows(tmp_path, rows)).errors
    assert has(errors, "e1_01", "room D", repr(value), "use 1 or leave it blank")
    assert not has(errors, "no room is labeled")  # one problem is reported once


def test_empty_row(tmp_path):
    rows = rows_for(default_labels())
    for room in ROOMS:
        rows[0][room] = ""
    assert has(check(write_rows(tmp_path, rows)).errors, "e1_01", "no room is labeled")


def test_row_with_more_cells_than_the_header(tmp_path):
    path = write_labels(tmp_path, default_labels())
    path.write_text(path.read_text().rstrip("\n") + ",extra,cells\n")  # extends the last row
    errors = check(path).errors
    assert has(errors, f"{COMMANDS[-1].id}: row has more cells than the header")


# ----------------------------------------------------------------- header

def test_missing_room_column(tmp_path):
    header = [h for h in HEADER if h != "LR"]
    errors = check(write_labels(tmp_path, default_labels(), header=header)).errors
    assert len(errors) == 1
    assert has(errors, "missing column(s): LR", "must match the scene graph")


def test_unexpected_and_duplicate_columns(tmp_path):
    rows = rows_for(default_labels())
    path = write_rows(tmp_path, rows, header=[*HEADER, "GARAGE"])
    assert has(check(path).errors, "unexpected column(s): 'GARAGE'")
    path = write_rows(tmp_path, rows, name="dup.csv", header=[*HEADER, "K"])
    assert has(check(path).errors, "duplicate column names")


def test_missing_id_column(tmp_path):
    header = [h for h in HEADER if h != "id"]
    assert has(check(write_labels(tmp_path, default_labels(), header=header)).errors,
               "missing column(s): id")


def test_empty_file_and_missing_file(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    assert has(check(empty).errors, "file is empty")
    with pytest.raises(LabelsError, match="cannot read"):
        check(tmp_path / "nope.csv")


# ----------------------------------------------------------------- expected_constraint (D-002)

@pytest.mark.parametrize("command_id, labeled, wrong_room", [
    ("e1_28", {"D"}, "D"),    # next to the kitchen: E or LR (K and D share a wall, no door)
    ("e1_31", {"K"}, "K"),    # next to the dining area: only LR
    ("e1_36", {"D"}, "D"),    # next to bedroom 2: only LR
])
def test_constraint_violations(tmp_path, command_id, labeled, wrong_room):
    labels = default_labels()
    labels[command_id] = labeled
    errors = check(write_labels(tmp_path, labels)).errors
    assert len(errors) == 1
    message = errors[0]
    assert command_id in message
    assert f"room {wrong_room} is labeled but is not allowed" in message
    assert "connected by a door" in message and "D-002" in message
    assert "share a wall" in message


def test_only_the_offending_rooms_are_reported(tmp_path):
    labels = default_labels()
    labels["e1_28"] = {"E", "D", "LR", "B1"}  # E and LR are allowed
    errors = check(write_labels(tmp_path, labels)).errors
    assert len(errors) == 2
    assert has(errors, "room D is labeled") and has(errors, "room B1 is labeled")


def test_allowed_labels_pass(tmp_path):
    labels = default_labels()
    labels["e1_28"] = {"E", "LR"}
    labels["e1_31"] = {"LR"}
    labels["e1_29"] = {"B1", "B2"}
    assert check(write_labels(tmp_path, labels)).ok


def test_unconstrained_commands_accept_any_room(tmp_path):
    labels = default_labels()
    labels["e1_01"] = {"B2"}
    assert check(write_labels(tmp_path, labels)).ok


# ----------------------------------------------------------------- more than 3 rooms

def test_more_than_three_rooms_is_a_warning_not_an_error(tmp_path):
    labels = default_labels()
    labels["e1_10"] = {"K", "D", "LR", "E"}
    report = check(write_labels(tmp_path, labels))
    assert report.ok
    assert len(report.warnings) == 1
    assert has(report.warnings, "e1_10", "4 rooms labeled", "aim for 1-3")


def test_three_rooms_is_fine(tmp_path):
    labels = default_labels()
    labels["e1_10"] = {"K", "D", "LR"}
    assert check(write_labels(tmp_path, labels)).warnings == []


# ----------------------------------------------------------------- compare

def test_compare_identical_files():
    labels = {cid: frozenset(rooms) for cid, rooms in default_labels().items()}
    comparison = compare_labels(labels, labels, COMMANDS, ROOMS)
    assert comparison.cell_agreement == 1.0
    assert comparison.mean_jaccard == 1.0
    assert comparison.identical == len(COMMANDS)
    assert comparison.disagreements == []
    assert "No disagreements." in format_comparison(comparison)


def test_compare_different_files():
    a = {cid: frozenset(rooms) for cid, rooms in default_labels().items()}
    b = dict(a)
    b["e1_10"] = frozenset({"K", "D"})  # A: K only
    b["e1_12"] = frozenset({"D"})       # A: K only
    comparison = compare_labels(a, b, COMMANDS, ROOMS)
    total = len(COMMANDS) * len(ROOMS)
    assert comparison.cells_total == total
    assert comparison.cells_agree == total - 3  # e1_10: D differs; e1_12: K and D differ
    assert comparison.jaccards["e1_10"] == 0.5
    assert comparison.jaccards["e1_12"] == 0.0
    assert comparison.identical == len(COMMANDS) - 2
    assert comparison.mean_jaccard == pytest.approx((len(COMMANDS) - 2 + 0.5) / len(COMMANDS))
    assert comparison.disagreements == [
        ("e1_10", BY_ID["e1_10"].command, (), ("D",)),
        ("e1_12", BY_ID["e1_12"].command, ("K",), ("D",)),
    ]
    text = format_comparison(comparison, "fileA.csv", "fileB.csv")
    assert "Disagreements (2):" in text
    assert "only in A" in text and "only in B" in text
    assert "e1_10" in text and BY_ID["e1_12"].command in text
    assert f"{(total - 3) / total:.4f}" in text


# ----------------------------------------------------------------- CLI

def test_cli_validate_ok(tmp_path, capsys):
    path = write_labels(tmp_path, default_labels())
    assert main(["validate", str(path)]) == 0
    assert capsys.readouterr().out.startswith(f"OK: {path}")


def test_cli_validate_prints_warnings_and_still_succeeds(tmp_path, capsys):
    labels = default_labels()
    labels["e1_10"] = {"K", "D", "LR", "E"}
    assert main(["validate", str(write_labels(tmp_path, labels))]) == 0
    captured = capsys.readouterr()
    assert "WARNING:" in captured.err and "1 warning(s)" in captured.out


def test_cli_validate_errors(tmp_path, capsys):
    labels = default_labels()
    labels["e1_28"] = {"D"}
    assert main(["validate", str(write_labels(tmp_path, labels))]) == 1
    err = capsys.readouterr().err
    assert "ERROR:" in err and "e1_28" in err and "room D" in err


def test_cli_unreadable_label_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.csv")]) == 1
    assert "cannot read" in capsys.readouterr().err


def test_cli_bad_commands_file(tmp_path, capsys):
    path = write_labels(tmp_path, default_labels())
    assert main(["validate", str(path), "--commands", str(tmp_path / "nope.json")]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_cli_compare(tmp_path, capsys):
    a = default_labels()
    b = default_labels()
    b["e1_12"] = {"D"}
    path_a = write_labels(tmp_path, a, name="a.csv")
    path_b = write_labels(tmp_path, b, name="b.csv")
    assert main(["compare", str(path_a), str(path_b)]) == 0
    out = capsys.readouterr().out
    assert "Cell agreement:" in out and "e1_12" in out and "Disagreements (1):" in out

    assert main(["compare", str(path_a), str(path_a)]) == 0
    assert "No disagreements." in capsys.readouterr().out


def test_cli_compare_refuses_an_invalid_file(tmp_path, capsys):
    good = write_labels(tmp_path, default_labels(), name="good.csv")
    bad_labels = default_labels()
    bad_labels["e1_36"] = {"D"}
    bad = write_labels(tmp_path, bad_labels, name="bad.csv")
    assert main(["compare", str(good), str(bad)]) == 1
    captured = capsys.readouterr()
    assert "room D" in captured.err
    assert "Cell agreement" not in captured.out


def test_compare_writes_nothing_to_data(tmp_path, capsys):
    before = sorted(p.name for p in DATA.iterdir())
    path = write_labels(tmp_path, default_labels())
    assert main(["compare", str(path), str(path)]) == 0
    capsys.readouterr()
    assert sorted(p.name for p in DATA.iterdir()) == before
