#!/usr/bin/env python3
"""Approach and touch one target object (proposal Step 4; D-098, D-099).

Needs house_nav.launch.py running (AMCL localized) and the scenario's objects spawned.
    ros2 run house_sim touch_target.py --name obj_bottle_0
    ros2 run house_sim touch_target.py --name obj_cell_phone_0 --scenario demo

1. Nav2 drives to a standoff pose 0.5 m in front of the target, facing it (closest free
   candidate first; up to --tries candidates).
2. A slow servo turns toward the target and drives forward until the bumper reports contact
   with it, the depth camera reads <= 0.15 m where the target is, or the pose-based gap
   estimate is <= 0.05 m. Contact with anything else stops it as a failure.

The target position comes from the scenario (same data as data/objects_<scenario>.json);
later it can come from a Detection message instead. Exit code 0 on success.
"""
import argparse
import math
import os
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
from touch_logic import (
    ServoParams,
    back_off_step,
    bearing_error,
    camera_bearing,
    depth_columns,
    gap,
    servo_step,
    standoff_candidates,
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
        self.depth = None
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
        self.depth = msg

    def current_contacts(self):
        if self.contact_time is None:
            return set()
        age = (self.node.get_clock().now() - self.contact_time).nanoseconds * 1e-9
        return self.contacts if age <= CONTACT_HOLD else set()

    def depth_min(self, cam_bearing, params):
        m = self.depth
        if m is None or m.encoding != "32FC1":
            return None
        d = np.frombuffer(bytes(m.data), dtype=np.float32).reshape(m.height, m.width)
        u0, u1 = depth_columns(m.width, cam_bearing, params)
        band = d[:, u0:u1]
        band = band[np.isfinite(band) & (band > 0)]
        return float(band.min()) if band.size else None


def robot_pose(tf_buffer):
    t = tf_buffer.lookup_transform("map", "base_link", Time())
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

    # AMCL is already localized (initial pose from the layout, D-062, then tracking). Waiting on
    # map_server instead of amcl skips BasicNavigator's initial-pose step, which would publish
    # a zero pose.
    nav.waitUntilNav2Active(localizer="map_server")
    while not tf_buffer.can_transform("map", "base_link", Time()):
        rclpy.spin_once(nav, timeout_sec=0.1)  # TF fills in on its own thread
    start = robot_pose(tf_buffer)

    # 1. Standoff with Nav2.
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

    def send(v, w):
        msg = TwistStamped()
        msg.header.stamp = nav.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.twist.linear.x, msg.twist.angular.z = v, w
        cmd.publish(msg)

    # 2. Servo until contact, depth or gap stop.
    t0 = nav.get_clock().now()
    last_report = None
    step, outcome = None, "timeout"
    while nav.get_clock().now() - t0 < Duration(seconds=args.touch_timeout):
        rclpy.spin_once(nav, timeout_sec=0.05)
        for _ in range(20):  # handle everything that is waiting (bumper, depth), not just one
            rclpy.spin_once(nav, timeout_sec=0.0)
        pose = robot_pose(tf_buffer)
        contacts = sensors.current_contacts()
        depth = sensors.depth_min(camera_bearing(pose, txy), params)  # camera is off-center
        step = servo_step(pose, txy, radius, args.name, contacts, depth, params)
        send(step.v, step.w)
        now = nav.get_clock().now()
        if last_report is None or now - last_report >= Duration(seconds=1.0):
            last_report = now
            print(f"    gap {gap(pose, txy, radius):.3f} m, bearing "
                  f"{math.degrees(bearing_error(pose, txy)):6.1f} deg, v {step.v:.2f}, "
                  f"w {step.w:+.2f}, depth {'-' if depth is None else f'{depth:.2f}'}, "
                  f"contacts {sorted(contacts) or '-'}", flush=True)
        if step.done:
            outcome = step.outcome
            break

    for _ in range(5):
        send(0.0, 0.0)
        rclpy.spin_once(nav, timeout_sec=0.05)

    pose = robot_pose(tf_buffer)
    ok = outcome in ("contact", "depth", "gap")
    print(f"RESULT {args.name}: {'SUCCEEDED' if ok else 'FAILED'} ({outcome}); "
          f"front-to-target gap {gap(pose, txy, radius):.3f} m (from AMCL), "
          f"bearing error {math.degrees(bearing_error(pose, txy)):.1f} deg", flush=True)

    # 3. Back off, so the robot is out of the target's lethal costmap zone for the next goal.
    if not args.no_back_off and gap(pose, txy, radius) < params.back_off_gap:
        t0, back = nav.get_clock().now(), "timeout"
        while nav.get_clock().now() - t0 < Duration(seconds=20.0):
            rclpy.spin_once(nav, timeout_sec=0.05)
            for _ in range(20):
                rclpy.spin_once(nav, timeout_sec=0.0)
            pose = robot_pose(tf_buffer)
            step = back_off_step(pose, txy, radius, args.name, sensors.current_contacts(),
                                 params)
            send(step.v, step.w)
            if step.done:
                back = step.outcome
                break
        for _ in range(5):
            send(0.0, 0.0)
            rclpy.spin_once(nav, timeout_sec=0.05)
        print(f"    backed off: {back}, gap {gap(robot_pose(tf_buffer), txy, radius):.3f} m",
              flush=True)
    # Stop the TF thread before shutdown; otherwise TransformListener.__del__ runs after
    # rclpy.shutdown() and prints a harmless but noisy InvalidHandle traceback.
    try:
        tf_listener.executor.shutdown()
        tf_listener.dedicated_listener_thread.join()
        tf_listener.dedicated_listener_thread = None
    except AttributeError:
        pass
    nav.destroy_node()
    tf_node.destroy_node()
    rclpy.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
