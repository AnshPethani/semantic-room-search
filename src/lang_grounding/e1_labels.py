"""E1 plausibility labels: validation and comparison (D-121, D-122). Pure Python, no ROS.

    python -m lang_grounding.e1_labels validate data/e1_labels_ansh.csv
    python -m lang_grounding.e1_labels compare data/e1_labels_ansh.csv data/e1_labels_kristika.csv

A label file is a CSV with the columns id, command, one column per room of the scene graph, and
(optionally) notes. A room cell is "1" (plausible) or blank. Nothing here writes any file.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lang_grounding.config import REPO_ROOT, load_config
from lang_grounding.scene_graph import load_scene_graph

DEFAULT_COMMANDS_PATH = REPO_ROOT / "data" / "e1_commands.json"
MAX_ROOMS_WITHOUT_WARNING = 3


class LabelsError(ValueError):
    """A label file or the E1 command file cannot be read or has an unusable structure."""


@dataclass(frozen=True)
class E1Command:
    id: str
    type: str
    command: str
    expected_constraint: tuple[str, ...] | None


@dataclass(frozen=True)
class LabelRow:
    line: int
    id: str
    command: str
    cells: dict[str, str]  # room ID -> stripped cell text
    notes: str
    extra_cells: bool = False  # the row had more cells than the header


@dataclass(frozen=True)
class ValidationReport:
    errors: list[str]
    warnings: list[str]
    labels: dict[str, frozenset[str]]  # command ID -> labeled rooms (complete only if no errors)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class Comparison:
    cells_agree: int
    cells_total: int
    jaccards: dict[str, float]
    disagreements: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]
    # (id, command, rooms only in A, rooms only in B), in command order

    @property
    def cell_agreement(self) -> float:
        return self.cells_agree / self.cells_total if self.cells_total else 1.0

    @property
    def mean_jaccard(self) -> float:
        return sum(self.jaccards.values()) / len(self.jaccards) if self.jaccards else 1.0

    @property
    def identical(self) -> int:
        return sum(1 for j in self.jaccards.values() if j == 1.0)


# --------------------------------------------------------------------------- E1 commands

def load_e1_commands(path: str | Path = DEFAULT_COMMANDS_PATH) -> list[E1Command]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LabelsError(f"cannot read E1 command file {p}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise LabelsError(f"{p} is not valid JSON: {exc}") from exc
    items = data.get("commands") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LabelsError(f'{p} must be a JSON object with a "commands" list')
    commands: list[E1Command] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) \
                or not isinstance(item.get("command"), str):
            raise LabelsError(f'{p}: command {i} needs string "id" and "command" fields')
        constraint = item.get("expected_constraint")
        if constraint is not None and (
                not isinstance(constraint, list) or not constraint
                or not all(isinstance(r, str) for r in constraint)):
            raise LabelsError(f"{p}: {item['id']}: expected_constraint must be null or a "
                              f"non-empty list of room IDs")
        if item["id"] in seen:
            raise LabelsError(f"{p}: duplicate command id {item['id']}")
        seen.add(item["id"])
        commands.append(E1Command(
            item["id"], str(item.get("type", "")), item["command"],
            None if constraint is None else tuple(constraint)))
    return commands


# --------------------------------------------------------------------------- reading CSV

def _check_header(path: Path, header: Sequence[str], room_ids: Sequence[str]) -> list[str]:
    errors = []
    if len(set(header)) != len(header):
        errors.append(f"{path}: header has duplicate column names")
    required = ["id", "command", *room_ids]
    missing = [c for c in required if c not in header]
    if missing:
        errors.append(
            f"{path}: header is missing column(s): {', '.join(missing)} "
            f"(room columns must match the scene graph: {', '.join(room_ids)})")
    unexpected = [c for c in header if c not in set(required) | {"notes"}]
    if unexpected:
        errors.append(
            f"{path}: header has unexpected column(s): "
            f"{', '.join(repr(c) for c in unexpected)}")
    return errors


def _read_rows(path: Path, room_ids: Sequence[str]) -> tuple[list[str], list[LabelRow]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return [f"{path}: file is empty (no header row)"], []
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            header_errors = _check_header(path, reader.fieldnames, room_ids)
            if header_errors:
                return header_errors, []
            rows = []
            for raw in reader:
                rows.append(LabelRow(
                    line=reader.line_num,
                    id=(raw.get("id") or "").strip(),
                    command=(raw.get("command") or "").strip(),
                    cells={r: (raw.get(r) or "").strip() for r in room_ids},
                    notes=(raw.get("notes") or "").strip(),
                    extra_cells=raw.get(None) is not None,
                ))
            return [], rows
    except OSError as exc:
        raise LabelsError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError:
        raise LabelsError(f"{path} is not valid UTF-8 text") from None
    except csv.Error as exc:
        raise LabelsError(f"{path}: invalid CSV: {exc}") from exc


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


# --------------------------------------------------------------------------- validation

def validate_labels(
    path: str | Path, commands: Sequence[E1Command], room_ids: Sequence[str]
) -> ValidationReport:
    """Check a label file against the E1 commands and the scene graph's room IDs (D-121)."""
    path = Path(path)
    header_errors, rows = _read_rows(path, room_ids)
    if header_errors:
        return ValidationReport(header_errors, [], {})

    by_id = {c.id: c for c in commands}
    errors: list[str] = []
    warnings: list[str] = []
    labels: dict[str, frozenset[str]] = {}
    seen: dict[str, LabelRow] = {}

    for row in rows:
        where = f"{path}:{row.line}"
        if not row.id:
            errors.append(f"{where}: row has no id")
            continue
        if row.id not in by_id:
            errors.append(f"{where}: unknown id {row.id!r} (not in the E1 command file)")
            continue
        if row.id in seen:
            errors.append(
                f"{where}: duplicate row for {row.id} (first one is at line {seen[row.id].line})")
            continue
        seen[row.id] = row
        cmd = by_id[row.id]

        if row.extra_cells:
            errors.append(f"{where}: {row.id}: row has more cells than the header")
        if not _same_text(row.command, cmd.command):
            errors.append(
                f"{where}: {row.id}: command {row.command!r} does not match the E1 command "
                f"{cmd.command!r}")

        bad_cells = False
        for room in room_ids:
            value = row.cells[room]
            if value not in ("", "1"):
                bad_cells = True
                errors.append(
                    f"{where}: {row.id}: room {room} has value {value!r}; "
                    f"use 1 or leave it blank")
        rooms = frozenset(r for r in room_ids if row.cells[r] == "1")
        labels[row.id] = rooms
        if not rooms and not bad_cells:
            errors.append(
                f"{where}: {row.id}: no room is labeled; every command needs at least one")

        if cmd.expected_constraint is not None:
            for room in room_ids:
                if room in rooms and room not in cmd.expected_constraint:
                    errors.append(
                        f"{where}: {row.id} ({cmd.command!r}): room {room} is labeled but is not "
                        f"allowed; this command allows only {', '.join(cmd.expected_constraint)}. "
                        f"\"Next to\" means connected by a door (D-002); rooms that only share a "
                        f"wall do not count")

        if len(rooms) > MAX_ROOMS_WITHOUT_WARNING:
            warnings.append(
                f"{where}: {row.id}: {len(rooms)} rooms labeled "
                f"({', '.join(r for r in room_ids if r in rooms)}); aim for 1-3")

    for cmd in commands:
        if cmd.id not in seen:
            errors.append(f"{path}: missing row for {cmd.id} ({cmd.command!r})")
    return ValidationReport(errors, warnings, labels)


# --------------------------------------------------------------------------- comparison

def compare_labels(
    a: Mapping[str, frozenset[str]],
    b: Mapping[str, frozenset[str]],
    commands: Sequence[E1Command],
    room_ids: Sequence[str],
) -> Comparison:
    """Cell agreement, per-command Jaccard and the disagreeing commands for two label sets."""
    agree = 0
    jaccards: dict[str, float] = {}
    disagreements = []
    for cmd in commands:
        la, lb = a[cmd.id], b[cmd.id]
        agree += sum(1 for r in room_ids if (r in la) == (r in lb))
        union = la | lb
        jaccards[cmd.id] = len(la & lb) / len(union) if union else 1.0
        if la != lb:
            disagreements.append((
                cmd.id, cmd.command,
                tuple(r for r in room_ids if r in la - lb),
                tuple(r for r in room_ids if r in lb - la)))
    return Comparison(agree, len(commands) * len(room_ids), jaccards, disagreements)


def format_comparison(
    comparison: Comparison, name_a: str = "A", name_b: str = "B"
) -> str:
    c = comparison
    n = len(c.jaccards)
    lines = [
        f"A: {name_a}",
        f"B: {name_b}",
        "",
        f"Commands compared: {n}",
        f"Cell agreement: {c.cell_agreement:.4f} ({c.cells_agree}/{c.cells_total} cells)",
        f"Mean per-command Jaccard: {c.mean_jaccard:.4f}",
        f"Identical commands: {c.identical}/{n}",
        "",
    ]
    if not c.disagreements:
        lines.append("No disagreements.")
        return "\n".join(lines)
    table = [("id", "command", "only in A", "only in B", "Jaccard")]
    for cid, command, only_a, only_b in c.disagreements:
        table.append((cid, command, ", ".join(only_a) or "-", ", ".join(only_b) or "-",
                      f"{c.jaccards[cid]:.2f}"))
    widths = [max(len(row[i]) for row in table) for i in range(5)]
    lines.append(f"Disagreements ({len(c.disagreements)}):")
    for row in table:
        lines.append("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
                     .rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI

def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--commands", help="E1 command file (default: data/e1_commands.json)")
    common.add_argument("--graph", help="scene graph JSON (default: from the config)")
    parser = argparse.ArgumentParser(
        prog="python -m lang_grounding.e1_labels",
        description="Validate and compare E1 plausibility label files.")
    sub = parser.add_subparsers(dest="action", required=True)
    v = sub.add_parser("validate", parents=[common], help="validate one label file")
    v.add_argument("file")
    c = sub.add_parser("compare", parents=[common], help="compare two valid label files")
    c.add_argument("file_a")
    c.add_argument("file_b")
    return parser


def _report(report: ValidationReport) -> None:
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in report.errors:
        print(f"ERROR: {error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 fine, 1 a label file is invalid, 2 the commands or graph cannot be loaded."""
    args = _build_parser().parse_args(argv)
    try:
        config = load_config()
        graph = load_scene_graph(args.graph or config.resolve(config.paths.scene_graph))
        commands = load_e1_commands(args.commands or DEFAULT_COMMANDS_PATH)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    room_ids = graph.room_ids

    paths = [args.file] if args.action == "validate" else [args.file_a, args.file_b]
    reports = []
    try:
        for path in paths:
            report = validate_labels(path, commands, room_ids)
            _report(report)
            reports.append(report)
    except LabelsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not all(r.ok for r in reports):
        n = sum(len(r.errors) for r in reports)
        print(f"{n} error(s); fix them before using or comparing the file(s).", file=sys.stderr)
        return 1

    if args.action == "validate":
        print(f"OK: {args.file} ({len(commands)} commands, {len(reports[0].warnings)} "
              f"warning(s))")
        return 0
    comparison = compare_labels(
        reports[0].labels, reports[1].labels, commands, room_ids)
    print(format_comparison(comparison, args.file_a, args.file_b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
