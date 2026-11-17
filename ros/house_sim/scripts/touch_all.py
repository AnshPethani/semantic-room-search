#!/usr/bin/env python3
"""Touch acceptance run: touch every object of a scenario in turn and check each against
Gazebo's true robot pose (D-094).

Needs house_nav.launch.py (or trial.launch.py) running with the scenario's objects spawned.
    ros2 run house_sim touch_all.py                          # every demo object
    ros2 run house_sim touch_all.py --names obj_cup_0 obj_cell_phone_0

Runs `touch_target.py --name <object> --truth` for each object (it backs off afterwards, so the
next one can start), prints its output as it comes, then a summary table. Exit code 0 if every
object passes: RESULT SUCCEEDED and TRUTH PASS (true gap <= 0.15 m while facing the object).
"""
import argparse
import os
import subprocess
import sys
import time

from ament_index_python.packages import get_package_share_directory
from house_objects import load_yaml, place_objects  # sibling scripts, installed together
from touch_check import parse_result, parse_truth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="demo")
    ap.add_argument("--names", nargs="+", help="only these objects, in this order")
    args, _ = ap.parse_known_args()

    share = get_package_share_directory("house_sim")
    layout = load_yaml(os.path.join(share, "layout", "house_layout.yaml"))
    catalog = load_yaml(os.path.join(share, "objects", "catalog.yaml"))
    path = args.scenario if os.path.isfile(args.scenario) else os.path.join(
        share, "objects", "scenarios", f"{args.scenario}.yaml")
    objects = [o["name"] for o in place_objects(layout, catalog, load_yaml(path))]
    names = args.names or objects
    unknown = [n for n in names if n not in objects]
    if unknown:
        print(f"ERROR: not in scenario {args.scenario}: {unknown}", file=sys.stderr)
        return 1

    rows = []
    for i, name in enumerate(names, 1):
        print(f"\n===== [{i}/{len(names)}] {name} =====", flush=True)
        t0 = time.monotonic()
        result = truth = None
        with subprocess.Popen(
                ["ros2", "run", "house_sim", "touch_target.py", "--name", name,
                 "--scenario", args.scenario, "--truth"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            for line in proc.stdout:
                print(line, end="", flush=True)
                result = parse_result(line) or result
                truth = parse_truth(line) or truth
        rows.append((name, result, truth, time.monotonic() - t0))

    print("\nTouch acceptance summary (true values from Gazebo)")
    print(f"  {'object':20s} {'result':22s} {'true gap':>9s} {'bearing':>8s}  check   time")
    passed = 0
    for name, result, truth, dt in rows:
        res = f"{'SUCCEEDED' if result[1] else 'FAILED'} ({result[2]})" if result else "no result"
        gap = f"{truth[1]:.3f} m" if truth else "-"
        bear = f"{truth[2]:.1f}" if truth else "-"
        ok = bool(result and result[1] and truth and truth[3])
        passed += ok
        print(f"  {name:20s} {res:22s} {gap:>9s} {bear:>8s}  {'PASS' if ok else 'FAIL':5s} "
              f"{dt / 60:5.1f} min")
    print(f"{passed}/{len(rows)} objects passed")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
