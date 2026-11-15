"""ROS-free tests for the robot model copy with a contact sensor and its bridge (D-095, D-096)."""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "ros" / "house_sim"
MODEL = PKG / "models" / "turtlebot3_waffle_bumper" / "model.sdf"
BRIDGE = PKG / "config" / "robot_bridge.yaml"
WORLD_LAUNCH = PKG / "launch" / "house_world.launch.py"

# Topics of the upstream turtlebot3_waffle_bridge.yaml (turtlebot3_gazebo 2.3.7).
UPSTREAM_TOPICS = {"clock", "joint_states", "odom", "tf", "cmd_vel", "imu", "scan",
                   "camera/camera_info"}


@pytest.fixture(scope="module")
def model():
    return ET.parse(MODEL).getroot().find("model")


@pytest.fixture(scope="module")
def bridge():
    return yaml.safe_load(BRIDGE.read_text(encoding="utf-8"))


def _floats(text):
    return [float(v) for v in text.split()]


def test_contact_sensor_on_the_body_collision(model):
    base = next(link for link in model.findall("link") if link.get("name") == "base_link")
    sensors = [s for s in base.findall("sensor") if s.get("type") == "contact"]
    assert len(sensors) == 1
    sensor = sensors[0]
    assert sensor.get("name") == "bumper"
    assert sensor.find("topic").text == "bumper"
    target = sensor.find("contact/collision").text
    assert target in {c.get("name") for c in base.findall("collision")}


def test_upstream_sensors_are_unchanged(model):
    sensors = {s.get("name"): s.get("type") for link in model.findall("link")
               for s in link.findall("sensor")}
    assert sensors == {"tb3_imu": "imu", "hls_lfcd_lds": "gpu_lidar", "camera": "camera",
                       "bumper": "contact"}


def test_bridge_keeps_upstream_topics_and_adds_bumper(bridge):
    topics = {e["ros_topic_name"]: e for e in bridge}
    assert set(topics) == UPSTREAM_TOPICS | {"bumper"}
    bumper = topics["bumper"]
    assert (bumper["gz_topic_name"], bumper["ros_type_name"], bumper["gz_type_name"],
            bumper["direction"]) == ("bumper", "ros_gz_interfaces/msg/Contacts",
                                     "gz.msgs.Contacts", "GZ_TO_ROS")


def test_cmd_vel_type_matches_nav2(bridge):
    cmd = next(e for e in bridge if e["ros_topic_name"] == "cmd_vel")
    assert cmd["ros_type_name"] == "geometry_msgs/msg/TwistStamped"
    params = yaml.safe_load((PKG / "config" / "nav2_params.yaml").read_text(encoding="utf-8"))
    assert params["controller_server"]["ros__parameters"]["enable_stamped_cmd_vel"] is True


def test_world_has_the_contact_system():
    world = (PKG / "worlds" / "house.sdf").read_text(encoding="utf-8")
    assert 'filename="gz-sim-contact-system"' in world


def test_world_launch_spawns_the_copy_with_the_new_bridge():
    text = WORLD_LAUNCH.read_text(encoding="utf-8")
    assert "'turtlebot3_waffle_bumper'" in text and "'robot_bridge.yaml'" in text
    assert "spawn_turtlebot3.launch.py" not in text  # upstream spawn would add a 2nd robot


def test_targets_lower_than_the_bumper_are_known(model):
    # Bottom of the body box above the floor: base_joint z + collision z - half its height.
    joint = next(j for j in model.findall("joint") if j.get("name") == "base_joint")
    base = next(link for link in model.findall("link") if link.get("name") == "base_link")
    col = next(c for c in base.findall("collision") if c.get("name") == "base_collision")
    bottom = (_floats(joint.find("pose").text)[2] + _floats(col.find("pose").text)[2]
              - _floats(col.find("geometry/box/size").text)[2] / 2)
    catalog = yaml.safe_load((PKG / "objects" / "catalog.yaml").read_text(encoding="utf-8"))
    heights = {}
    for label, spec in catalog["classes"].items():
        heights[label] = {"box": lambda s: s["size"][2], "cylinder": lambda s: s["length"],
                          "sphere": lambda s: 2 * s["radius"]}[spec["shape"]](spec)
    # The bumper cannot touch these; the touch step must use the depth stop for them (D-095).
    assert {label for label, h in heights.items() if h <= bottom} == {"cell phone"}
