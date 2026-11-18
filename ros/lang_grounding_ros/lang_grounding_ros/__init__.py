"""Thin ROS 2 wrapper around the lang_grounding library (D-129).

This package imports neither rclpy nor semantic_msgs except in ground_command_node.py, so the
other modules can be tested without ROS.
"""
