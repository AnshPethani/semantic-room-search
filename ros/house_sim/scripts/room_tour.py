#!/usr/bin/env python3
"""Nav2 acceptance check: drive to one goal in every room and report the result (D-064).

Start house_nav.launch.py first, then (robot still at the start pose):
    ros2 run house_sim room_tour.py                 # K LR D B2 B1 E
    ros2 run house_sim room_tour.py --rooms K D     # a subset, in this order

Exit code 0 if every goal succeeded, 1 otherwise.
"""
import argparse
import math
import os
import sys
import time

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.parameter import Parameter

from room_goals import room_goals

DEFAULT_ORDER = ["K", "LR", "D", "B2", "B1", "E"]


def make_pose(nav, x, y, yaw=0.0):
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.header.stamp = nav.get_clock().now().to_msg()
    pose.pose.position.x = float(x)
    pose.pose.position.y = float(y)
    pose.pose.orientation.z = math.sin(yaw / 2)
    pose.pose.orientation.w = math.cos(yaw / 2)
    return pose


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", nargs="+", default=DEFAULT_ORDER)
    ap.add_argument("--timeout", type=float, default=180.0, help="seconds per goal")
    args, _ = ap.parse_known_args()

    share = get_package_share_directory("house_sim")
    with open(os.path.join(share, "layout", "house_layout.yaml"), encoding="utf-8") as f:
        layout = yaml.safe_load(f)
    goals = room_goals(layout["rooms"])
    unknown = [r for r in args.rooms if r not in goals]
    if unknown:
        print(f"ERROR: unknown rooms {unknown}; known: {list(goals)}", file=sys.stderr)
        return 1

    rclpy.init()
    nav = BasicNavigator()
    nav.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])

    # BasicNavigator republishes its stored initial pose (zero by default) until AMCL answers,
    # so set the real start pose from the layout first (D-062).
    s = layout["robot_start"]
    nav.setInitialPose(make_pose(nav, s["x"], s["y"], s.get("yaw", 0.0)))
    nav.waitUntilNav2Active()

    results = []
    for rid in args.rooms:
        x, y, clearance = goals[rid]
        print(f"--> {rid}: goal ({x:.2f}, {y:.2f}), clearance {clearance:.2f} m", flush=True)
        t0 = time.monotonic()
        if not nav.goToPose(make_pose(nav, x, y)):
            results.append((rid, "REJECTED", 0.0))
            continue
        canceled = False
        while not nav.isTaskComplete():
            if not canceled and time.monotonic() - t0 > args.timeout:
                nav.cancelTask()
                canceled = True
        result = nav.getResult()
        name = {TaskResult.SUCCEEDED: "SUCCEEDED", TaskResult.CANCELED: "TIMEOUT",
                TaskResult.FAILED: "FAILED"}.get(result, str(result))
        results.append((rid, name, time.monotonic() - t0))
        print(f"    {rid}: {name} in {results[-1][2]:.1f} s", flush=True)

    print("\nRoom tour summary")
    for rid, name, dt in results:
        print(f"  {rid:3s} {name:9s} {dt:6.1f} s")
    ok = all(name == "SUCCEEDED" for _, name, _ in results)
    print("ALL ROOMS REACHED" if ok else "SOME ROOMS FAILED")
    nav.destroy_node()
    rclpy.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
