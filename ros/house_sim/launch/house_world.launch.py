"""Start Gazebo Harmonic with the house world and spawn a TurtleBot3 at the start pose.

    ros2 launch house_sim house_world.launch.py               # with GUI
    ros2 launch house_sim house_world.launch.py gui:=false    # headless (for batch trials)
    ros2 launch house_sim house_world.launch.py x_pose:=6.0 y_pose:=3.0
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    AppendEnvironmentVariable,
    DeclareLaunchArgument,
    IncludeLaunchDescription,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # turtlebot3_gazebo's spawn file reads this env var; default to the Waffle.
    os.environ.setdefault('TURTLEBOT3_MODEL', 'waffle')

    pkg = get_package_share_directory('house_sim')
    tb3 = get_package_share_directory('turtlebot3_gazebo')
    ros_gz_sim = get_package_share_directory('ros_gz_sim')
    world = os.path.join(pkg, 'worlds', 'house.sdf')

    # The layout is the single source of truth for the start pose (D-055).
    with open(os.path.join(pkg, 'layout', 'house_layout.yaml')) as f:
        start = yaml.safe_load(f)['robot_start']

    gui = LaunchConfiguration('gui')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('x_pose', default_value=str(start['x'])),
        DeclareLaunchArgument('y_pose', default_value=str(start['y'])),

        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(tb3, 'models')),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(pkg, 'models')),

        # Gazebo server (physics + sensors)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={'gz_args': ['-r -s -v2 ', world],
                              'on_exit_shutdown': 'true'}.items()),
        # Gazebo GUI (optional)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={'gz_args': '-g -v2 ', 'on_exit_shutdown': 'true'}.items(),
            condition=IfCondition(gui)),

        # robot_state_publisher, spawn, and ros_gz bridges (scan, odom, tf, cmd_vel, camera)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(tb3, 'launch', 'robot_state_publisher.launch.py')),
            launch_arguments={'use_sim_time': use_sim_time}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(tb3, 'launch', 'spawn_turtlebot3.launch.py')),
            launch_arguments={'x_pose': LaunchConfiguration('x_pose'),
                              'y_pose': LaunchConfiguration('y_pose')}.items()),
    ])
