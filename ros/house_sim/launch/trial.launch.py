"""One trial setup in one command: house world + Nav2 + target objects + seeded clutter (D-093).

    ros2 launch house_sim trial.launch.py                        # demo targets, no clutter
    ros2 launch house_sim trial.launch.py clutter_count:=10 clutter_seed:=3
    ros2 launch house_sim trial.launch.py scenario:=none gui:=false rviz:=false

The same scenario, clutter_count and clutter_seed always give the same world (proposal: fixed
seed list, identical conditions for every method). Objects and clutter are spawned after
spawn_delay seconds, once Gazebo is up.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression


def generate_launch_description():
    pkg = get_package_share_directory('house_sim')
    launch_dir = os.path.join(pkg, 'launch')
    scenario = LaunchConfiguration('scenario')
    count = LaunchConfiguration('clutter_count')

    return LaunchDescription([
        DeclareLaunchArgument('scenario', default_value='demo',
                              description='target scenario in objects/scenarios/, or none'),
        DeclareLaunchArgument('clutter_count', default_value='0', description='0-10'),
        DeclareLaunchArgument('clutter_seed', default_value='0'),
        DeclareLaunchArgument('spawn_delay', default_value='20.0',
                              description='s (wall clock) to wait for Gazebo before spawning'),
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(launch_dir, 'house_nav.launch.py')),
            launch_arguments={'gui': LaunchConfiguration('gui'),
                              'rviz': LaunchConfiguration('rviz')}.items()),

        TimerAction(period=LaunchConfiguration('spawn_delay'), actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(os.path.join(launch_dir, 'spawn_objects.launch.py')),
                launch_arguments={'scenario': scenario}.items(),
                condition=IfCondition(PythonExpression(["'", scenario, "' != 'none'"]))),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(os.path.join(launch_dir, 'spawn_clutter.launch.py')),
                launch_arguments={'count': count, 'seed': LaunchConfiguration('clutter_seed'),
                                  'scenario': scenario}.items(),
                condition=IfCondition(PythonExpression([count, ' > 0']))),
        ]),
    ])
