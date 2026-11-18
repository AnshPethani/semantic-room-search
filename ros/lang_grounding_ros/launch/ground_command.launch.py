"""Start the /ground_command service with repo-relative defaults.

    ros2 launch lang_grounding_ros ground_command.launch.py
    ros2 launch lang_grounding_ros ground_command.launch.py backend:=fake
    ros2 launch lang_grounding_ros ground_command.launch.py repo_root:=/path/to/semantic-room-search

The repository root is found from this file (it works from a `colcon build --symlink-install`
workspace, where the installed launch file is a link into the repository), or from the
SEMANTIC_ROOM_SEARCH_ROOT environment variable, or from the `repo_root` argument. The node
gets <repo>/src on its PYTHONPATH, so the lang_grounding library is imported from the repository.
"""

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import (
    EnvironmentVariable,
    LaunchConfiguration,
    PathJoinSubstitution,
    TextSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_root = (os.environ.get("SEMANTIC_ROOM_SEARCH_ROOT")
                    or str(Path(__file__).resolve().parents[3]))
    root = LaunchConfiguration("repo_root")

    node = Node(
        package="lang_grounding_ros",
        executable="ground_command_node",
        name="ground_command",
        output="screen",
        parameters=[{
            "scene_graph_file": PathJoinSubstitution([root, "data", "scene_graph.json"]),
            "vocabulary_file": PathJoinSubstitution([root, "configs", "vocabulary.json"]),
            "config_file": PathJoinSubstitution([root, "configs", "grounding.json"]),
            "env_file": PathJoinSubstitution([root, ".env"]),
            "log_dir": PathJoinSubstitution([root, "logs"]),
            "backend": LaunchConfiguration("backend"),
            "timeout_s": ParameterValue(LaunchConfiguration("timeout_s"), value_type=float),
        }],
        additional_env={
            "PYTHONPATH": [
                PathJoinSubstitution([root, "src"]),
                TextSubstitution(text=":"),
                EnvironmentVariable("PYTHONPATH", default_value=""),
            ],
        },
    )
    return LaunchDescription([
        DeclareLaunchArgument("repo_root", default_value=default_root,
                              description="root of the semantic-room-search repository"),
        DeclareLaunchArgument("backend", default_value="gemini",
                              description="gemini, ollama or fake"),
        DeclareLaunchArgument("timeout_s", default_value="20.0",
                              description="seconds before a call is answered with a timeout"),
        node,
    ])
