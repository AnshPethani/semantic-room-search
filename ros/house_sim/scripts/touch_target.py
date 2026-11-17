#!/usr/bin/env python3
"""Approach and touch one target object (proposal Step 4; D-098, D-099).

Needs house_nav.launch.py running (AMCL localized) and the scenario's objects spawned.
    ros2 run house_sim touch_target.py --name obj_bottle_0
    ros2 run house_sim touch_target.py --name obj_cell_phone_0 --scenario demo

1. Nav2 drives to a standoff pose 0.5 m in front of the target, facing it (closest free
   candidate first; up to --tries candidates).
2. The final approach runs on wheel odometry (odom frame). The target estimate starts from its
   known position and is corrected by the depth camera whenever the target is in view (floor
   pixels ignored). A slow servo turns toward the estimate and drives until the bumper reports
   contact with the target, its depth is <= 0.15 m, or the estimated gap is <= 0.05 m (for
   objects too low for the camera at close range). Contact with anything else is a failure.
3. The robot backs off to a 0.30 m gap, so Nav2 can plan the next goal.

The target position comes from the scenario (same data as data/objects_<scenario>.json);
later it can come from a Detection message instead. Exit code 0 on success.
"""
import argparse
import math
import os
import subprocess
import sys

import numpy as np
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped, TwistStamped
from house_objects import load_yaml, place_objects  # sibling scripts, installed together
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from rclpy.time import Time
from ros_gz_interfaces.msg import Contacts
from sensor_msgs.msg import Image
from tf2_ros import Buffer, TransformListener
from touch_check import parse_gz_pose, touch_ok, true_touch
from touch_logic import (
    ServoParams,
    back_off_step,
    bearing_error,
    gap,
    near_side_height,
    servo_step,
    standoff_candidates,
    track,
    transfer,
)

ROBOT_MODEL = "waffle"       # Gazebo model name of the robot (house_world.launch.py)
CONTACT_HOLD = 0.3           # s (sim): a contact counts as current for this long


def make_pose(nav, x, y, yaw):
    p = PoseStamped()
    p.header.frame_id = "map"
    p.header.stamp = nav.get_clock().now().to_msg()
    p.pose.position.x, p.pose.position.y = float(x), float(y)
    p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
    return p


class Sensors:
    """Latest bumper contacts and depth image, filled by subscriptions on the navigator node."""

    def __init__(self, node):
        self.node = node
        self.contacts, self.contact_time = set(), None
        self.depth, self.depth_seq = None, 0
        node.create_subscription(Contacts, "/bumper", self._on_contacts, 10)
        node.create_subscription(Image, "/camera/depth/image_raw", self._on_depth, 1)

    def _on_contacts(self, msg):
        models = set()
        for c in msg.contacts:
            for col in (c.collision1, c.collision2):
                model = col.name.split("::")[0]
                if model and model != ROBOT_MODEL:
                    models.add(model)
        if models:
            self.contacts, self.contact_time = models, self.node.get_clock().now()

    def _on_depth(self, msg):
        if msg.encoding == "32FC1":
            self.depth = np.frombuffer(bytes(msg.data), dtype=np.float32).reshape(
                msg.height, msg.width)
            self.depth_seq += 1

    def current_contacts(self):
        if self.contact_time is None:
            return set()
        age = (self.node.get_clock().now() - self.contact_time).nanoseconds * 1e-9
        return self.contacts if age <= CONTACT_HOLD else set()


def lookup_pose(tf_buffer, frame):
    """(x, y, yaw) of base_link in `frame` (map: AMCL; odom: wheel odometry)."""
    t = tf_buffer.lookup_transform(frame, "base_link", Time())
    q = t.transform.rotation
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
    return (t.transform.translation.x, t.transform.translation.y, yaw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="Gazebo model name, e.g. obj_bottle_0")
    ap.add_argument("--scenario", default="demo")
    ap.add_argument("--tries", type=int, default=4, help="standoff candidates to try")
    ap.add_argument("--nav-timeout", type=float, default=300.0, help="s (sim) per standoff")
    ap.add_argument("--touch-timeout", type=float, default=60.0, help="s (sim) for the servo")
    ap.add_argument("--no-back-off", action="store_true",
                    help="stay at the target after the touch (Nav2 cannot plan from there)")
    ap.add_argument("--truth", action="store_true",
                    help="after the touch, check it against Gazebo's true robot pose (D-094)")
    args, _ = ap.parse_known_args()

    share = get_package_share_directory("house_sim")
    layout = load_yaml(os.path.join(share, "layout", "house_layout.yaml"))
    catalog = load_yaml(os.path.join(share, "objects", "catalog.yaml"))
    scenario_path = args.scenario if os.path.isfile(args.scenario) else os.path.join(
        share, "objects", "scenarios", f"{args.scenario}.yaml")
    with open(scenario_path, encoding="utf-8") as f:
        objects = place_objects(layout, catalog, yaml.safe_load(f))
    target = next((o for o in objects if o["name"] == args.name), None)
    if target is None:
        print(f"ERROR: no object {args.name} in scenario {args.scenario}; known: "
              f"{', '.join(o['name'] for o in objects)}", file=sys.stderr)
        return 1
    txy, radius = (target["x"], target["y"]), target["radius"]
    near_h = near_side_height(catalog["classes"][target["label"]])

    rclpy.init()
    nav = BasicNavigator()
    nav.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
    sensors = Sensors(nav)
    # TF gets its own node and thread so the robot pose is always current; on the navigator
    # node it competes with depth images for spin_once and goes stale (seen 2026-11-15).
    tf_node = rclpy.create_node(
        "touch_target_tf",
        parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)])
    tf_buffer = Buffer()
    tf_listener = TransformListener(tf_buffer, tf_node, spin_thread=True)
    cmd = nav.create_publisher(TwistStamped, "/cmd_vel", 10)
    params = ServoParams()

    def send(v, w):
        msg = TwistStamped()
        msg.header.stamp = nav.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.twist.linear.x, msg.twist.angular.z = v, w
        cmd.publish(msg)

    def spin_all():
        rclpy.spin_once(nav, timeout_sec=0.05)
        for _ in range(20):  # handle everything that is waiting (bumper, depth), not just one
            rclpy.spin_once(nav, timeout_sec=0.0)

    # No waitUntilNav2Active(): it asks lifecycle nodes for their state with no timeout, and
    # under WSL a lost service reply hung the run forever (2026-11-16). goToPose() already
    # waits for the NavigateToPose action server, which exists only once Nav2 is up. AMCL is
    # already localized (initial pose from the layout, D-062), so no initial pose is sent.
    while not (tf_buffer.can_transform("map", "base_link", Time())
               and tf_buffer.can_transform("odom", "base_link", Time())):
        rclpy.spin_once(nav, timeout_sec=0.1)  # TF fills in on its own thread
    start = lookup_pose(tf_buffer, "map")

    # 1. Standoff with Nav2 (map frame).
    reached = None
    for x, y, yaw in standoff_candidates(layout, txy, radius, start[:2])[:args.tries]:
        print(f"--> standoff ({x:.2f}, {y:.2f}) facing {args.name}", flush=True)
        nav.goToPose(make_pose(nav, x, y, yaw))
        t0, canceled = nav.get_clock().now(), False
        while not nav.isTaskComplete():
            if not canceled and nav.get_clock().now() - t0 > Duration(seconds=args.nav_timeout):
                nav.cancelTask()
                canceled = True
        if nav.getResult() == TaskResult.SUCCEEDED:
            reached = (x, y)
            break
        print("    standoff not reached, trying the next one", flush=True)
    if reached is None:
        print(f"RESULT {args.name}: FAILED (no standoff reached)")
        return 1

    # 2. Final approach in the odom frame: move the target estimate from map to odom once
    #    (through the robot's AMCL and odometry poses at this instant), then track it.
    map_pose, odom_pose = lookup_pose(tf_buffer, "map"), lookup_pose(tf_buffer, "odom")
    est = transfer(txy, map_pose, odom_pose)
    t0, last_report, last_seq = nav.get_clock().now(), None, -1
    step, outcome, sightings, last_depth = None, "timeout", 0, None
    while nav.get_clock().now() - t0 < Duration(seconds=args.touch_timeout):
        spin_all()
        pose = lookup_pose(tf_buffer, "odom")
        depth = None
        if sensors.depth is not None and sensors.depth_seq != last_seq:
            last_seq = sensors.depth_seq
            img = sensors.depth
            h, w = img.shape
            est, depth = track(pose, est, radius, near_h,
                               lambda u, v, img=img: float(img[v, u]), w, h, params,
                               acquired=sightings > 0)
            sightings += depth is not None
            if depth is not None:
                last_depth = depth
        contacts = sensors.current_contacts()
        step = servo_step(pose, est, radius, args.name, contacts, depth, params,
                          seen=sightings > 0)
        send(step.v, step.w)
        now = nav.get_clock().now()
        if last_report is None or now - last_report >= Duration(seconds=1.0):
            last_report = now
            print(f"    gap {gap(pose, est, radius):.3f} m, bearing "
                  f"{math.degrees(bearing_error(pose, est)):6.1f} deg, v {step.v:.2f}, "
                  f"w {step.w:+.2f}, last depth "
                  f"{'-' if last_depth is None else f'{last_depth:.2f}'}, "
                  f"sightings {sightings}, contacts {sorted(contacts) or '-'}", flush=True)
        if step.done:
            outcome = step.outcome
            break

    for _ in range(5):
        send(0.0, 0.0)
        rclpy.spin_once(nav, timeout_sec=0.05)

    pose = lookup_pose(tf_buffer, "odom")
    shift = math.dist(est, transfer(txy, map_pose, odom_pose))
    ok = outcome in ("contact", "depth", "gap")
    print(f"RESULT {args.name}: {'SUCCEEDED' if ok else 'FAILED'} ({outcome}); "
          f"front-to-target gap {gap(pose, est, radius):.3f} m, bearing error "
          f"{math.degrees(bearing_error(pose, est)):.1f} deg; depth sightings {sightings}, "
          f"estimate moved {shift:.3f} m from the AMCL-based start", flush=True)

    if args.truth:  # before the back-off, while the robot is still at the target
        try:
            out = subprocess.run(["gz", "model", "-m", ROBOT_MODEL, "-p"], capture_output=True,
                                 text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            out = ""
            print(f"    truth check: gz failed ({exc})", flush=True)
        true_pose = parse_gz_pose(out)
        if true_pose is None:
            print(f"TRUTH {args.name}: no Gazebo pose", flush=True)
        else:
            tgap, tbear = true_touch(true_pose, txy, catalog["classes"][target["label"]],
                                     target["yaw"])
            print(f"TRUTH {args.name}: gap {tgap:.3f} m, bearing {math.degrees(tbear):.1f} deg, "
                  f"{'PASS' if touch_ok(tgap, tbear) else 'FAIL'} (Gazebo pose "
                  f"{true_pose[0]:.3f} {true_pose[1]:.3f} {true_pose[2]:.3f})", flush=True)

    # 3. Back off, so the robot is out of the target's lethal costmap zone for the next goal.
    if not args.no_back_off and gap(pose, est, radius) < params.back_off_gap:
        t0, back = nav.get_clock().now(), "timeout"
        while nav.get_clock().now() - t0 < Duration(seconds=20.0):
            spin_all()
            pose = lookup_pose(tf_buffer, "odom")
            step = back_off_step(pose, est, radius, args.name, sensors.current_contacts(),
                                 params)
            send(step.v, step.w)
            if step.done:
                back = step.outcome
                break
        for _ in range(5):
            send(0.0, 0.0)
            rclpy.spin_once(nav, timeout_sec=0.05)
        print(f"    backed off: {back}, gap "
              f"{gap(lookup_pose(tf_buffer, 'odom'), est, radius):.3f} m", flush=True)

    # Stop the TF thread before shutdown; otherwise TransformListener.__del__ runs after
    # rclpy.shutdown() and prints a harmless but noisy InvalidHandle traceback.
    # (Shutting down twice is harmless, and joining a finished thread returns at once, so the
    # listener's own __del__ can repeat both later.)
    try:
        tf_listener.executor.shutdown()
        tf_listener.dedicated_listener_thread.join()
    except AttributeError:
        pass
    nav.destroy_node()
    tf_node.destroy_node()
    rclpy.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
