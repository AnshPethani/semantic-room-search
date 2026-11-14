"""Spawn random clutter (not on the map) into the running house world (D-092).

    ros2 launch house_sim spawn_clutter.launch.py                     # 5 objects, seed 0
    ros2 launch house_sim spawn_clutter.launch.py count:=10 seed:=3
    ros2 launch house_sim spawn_clutter.launch.py scenario:=none      # ignore target objects

The same count and seed always give the same placement. Clutter keeps clear of the target
objects of `scenario` (default: demo), so spawn those with the same scenario. Placement takes
a few seconds (viewpoints and a reachability check are computed first).
"""
import os
import sys

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _spawn(context):
    share = get_package_share_directory('house_sim')
    sys.path.insert(0, os.path.join(get_package_prefix('house_sim'), 'lib', 'house_sim'))
    import clutter
    import house_objects

    count = int(LaunchConfiguration('count').perform(context))
    seed = int(LaunchConfiguration('seed').perform(context))
    scenario = LaunchConfiguration('scenario').perform(context)

    layout = house_objects.load_yaml(os.path.join(share, 'layout', 'house_layout.yaml'))
    targets = []
    if scenario not in ('', 'none'):
        path = scenario if os.path.isfile(scenario) else os.path.join(
            share, 'objects', 'scenarios', f'{scenario}.yaml')
        catalog = house_objects.load_yaml(os.path.join(share, 'objects', 'catalog.yaml'))
        targets = house_objects.place_objects(layout, catalog, house_objects.load_yaml(path))
    types = house_objects.load_yaml(os.path.join(share, 'objects', 'clutter.yaml'))
    placed = clutter.place_clutter(layout, types, count, seed, targets=targets)

    actions = [LogInfo(msg=f'clutter seed {seed}: ' + (', '.join(
        f"{o['name']} in {o['room']} at ({o['x']:.2f}, {o['y']:.2f})" for o in placed)
        or 'none'))]
    actions += [
        Node(package='ros_gz_sim', executable='create', output='screen',
             arguments=['-world', 'house', '-name', o['name'], '-string', o['sdf'],
                        '-x', str(o['x']), '-y', str(o['y']), '-z', str(o['z']),
                        '-Y', str(o['yaw'])])
        for o in placed
    ]
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('count', default_value='5', description='0-10 clutter objects'),
        DeclareLaunchArgument('seed', default_value='0', description='random seed'),
        DeclareLaunchArgument('scenario', default_value='demo',
                              description='target scenario to keep clear of, or none'),
        OpaqueFunction(function=_spawn),
    ])
