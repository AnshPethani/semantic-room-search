"""Spawn the target objects of a scenario into the running house world (D-073).

    ros2 launch house_sim spawn_objects.launch.py                    # scenarios/demo.yaml
    ros2 launch house_sim spawn_objects.launch.py scenario:=my_scene # scenarios/my_scene.yaml
    ros2 launch house_sim spawn_objects.launch.py scenario:=/abs/path.yaml

(scenario names refer to objects/scenarios/<name>.yaml)

Start house_world.launch.py or house_nav.launch.py first. The scenario is checked against the
placement rules before anything is spawned; a broken rule stops the launch with an error.
"""
import os
import sys

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _spawn(context):
    share = get_package_share_directory('house_sim')
    # house_objects.py is ROS-free and installed next to the other scripts.
    sys.path.insert(0, os.path.join(get_package_prefix('house_sim'), 'lib', 'house_sim'))
    import house_objects

    scenario = LaunchConfiguration('scenario').perform(context)
    path = scenario if os.path.isfile(scenario) else os.path.join(
        share, 'objects', 'scenarios', f'{scenario}.yaml')
    layout = house_objects.load_yaml(os.path.join(share, 'layout', 'house_layout.yaml'))
    catalog = house_objects.load_yaml(os.path.join(share, 'objects', 'catalog.yaml'))
    objects = house_objects.place_objects(layout, catalog, house_objects.load_yaml(path))

    return [
        Node(package='ros_gz_sim', executable='create', output='screen',
             arguments=['-world', 'house', '-name', o['name'], '-string', o['sdf'],
                        '-x', str(o['x']), '-y', str(o['y']), '-z', str(o['z']),
                        '-Y', str(o['yaw'])])
        for o in objects
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('scenario', default_value='demo',
                              description='scenario name in objects/scenarios/, or a file path'),
        OpaqueFunction(function=_spawn),
    ])
