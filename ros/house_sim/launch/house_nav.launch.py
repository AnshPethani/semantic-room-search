"""Gazebo house + Nav2 on the known map (map_server, AMCL, planner, controller) + RViz (D-060).

    ros2 launch house_sim house_nav.launch.py                        # Gazebo GUI + RViz
    ros2 launch house_sim house_nav.launch.py gui:=false rviz:=false # headless

No SLAM: the map is maps/house_map.yaml, generated from the same layout as the world.
AMCL's initial pose is set in config/nav2_params.yaml to the layout's robot_start (D-062),
so the robot is localized without clicking "2D Pose Estimate".
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    pkg = get_package_share_directory('house_sim')
    nav2 = get_package_share_directory('nav2_bringup')

    gui = LaunchConfiguration('gui')
    rviz = LaunchConfiguration('rviz')

    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true', description='Gazebo GUI'),
        DeclareLaunchArgument('rviz', default_value='true', description='RViz with Nav2 panel'),

        # World + robot at robot_start (same pose AMCL starts from).
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(pkg, 'launch', 'house_world.launch.py')),
            launch_arguments={'gui': gui, 'use_sim_time': 'true'}.items()),

        # map_server + AMCL + navigation servers, all lifecycle-managed.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(nav2, 'launch', 'bringup_launch.py')),
            launch_arguments={
                'map': os.path.join(pkg, 'maps', 'house_map.yaml'),
                'params_file': os.path.join(pkg, 'config', 'nav2_params.yaml'),
                'use_sim_time': 'true',
                'autostart': 'true',
            }.items()),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(nav2, 'launch', 'rviz_launch.py')),
            launch_arguments={'use_sim_time': 'true'}.items(),
            condition=IfCondition(rviz)),
    ])
