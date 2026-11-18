"""The /ground_command service node (D-129 to D-131). Thin: all logic is in the library.

    ros2 run lang_grounding_ros ground_command_node --ros-args -p backend:=fake

See docs/ROS.md for the setup in the pixi environment.
"""

from __future__ import annotations

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.logging import get_logger
from rclpy.node import Node
from semantic_msgs.msg import RoomProb
from semantic_msgs.srv import GroundCommand

try:
    from .grounder import build_handler
except ImportError as exc:  # the library is not on the Python path
    raise ImportError(
        "cannot import the lang_grounding library or one of its dependencies "
        f"({exc}); put <repo>/src on PYTHONPATH and install pydantic, see docs/ROS.md"
    ) from exc
from .mapping import failure_fields, short_error

SERVICE_NAME = "/ground_command"
EXECUTOR_THREADS = 4
PARAMETERS = {
    "scene_graph_file": "",   # empty: the default in configs/grounding.json
    "vocabulary_file": "",
    "config_file": "",
    "env_file": "",           # empty: .env at the repository root
    "log_dir": "",            # empty: the log path in configs/grounding.json
    "backend": "gemini",      # gemini, ollama or fake
    "timeout_s": 20.0,
}


def fill_response(response, fields: dict) -> None:
    """Copy the plain response fields (see mapping.py) into a GroundCommand response."""
    response.success = fields["success"]
    response.error = fields["error"]
    response.targets = list(fields["targets"])
    response.room_prior = [RoomProb(room_id=room, prob=prob) for room, prob in fields["room_prior"]]
    response.room_constraint = list(fields["room_constraint"])
    response.rationale = fields["rationale"]
    response.latency_s = fields["latency_s"]
    response.model = fields["model"]
    response.cache_hit = fields["cache_hit"]
    response.source = fields["source"]


class GroundCommandNode(Node):
    def __init__(self) -> None:
        super().__init__("ground_command")
        params = {name: self.declare_parameter(name, default).value
                  for name, default in PARAMETERS.items()}
        # Loaded once, here. A setup problem raises a ValueError that main() reports.
        self._setup = build_handler(
            scene_graph_file=params["scene_graph_file"],
            vocabulary_file=params["vocabulary_file"],
            config_file=params["config_file"],
            env_file=params["env_file"],
            log_dir=params["log_dir"],
            backend=params["backend"],
            timeout_s=float(params["timeout_s"]),
        )
        for note in self._setup.notes:
            self.get_logger().warning(note)
        self.get_logger().info(self._setup.summary)
        # Reentrant group plus a multi-threaded executor: a slow call does not block others.
        self._group = ReentrantCallbackGroup()
        self._service = self.create_service(
            GroundCommand, SERVICE_NAME, self._on_request, callback_group=self._group)
        self.get_logger().info(f"service {SERVICE_NAME} ready")

    def _on_request(self, request, response):
        try:
            fields = self._setup.handler.handle(request.command)
            fill_response(response, fields)
        except Exception as exc:  # an exception in a callback would stop the executor
            fields = failure_fields(short_error(exc))
            fill_response(response, fields)
        if fields["success"]:
            self.get_logger().info(
                f"ground {request.command!r}: {fields['source']} in {fields['latency_s']:.2f} s")
        else:
            self.get_logger().warning(f"ground {request.command!r} failed: {fields['error']}")
        return response

    def close(self) -> None:
        self._setup.handler.close()


def main(args=None) -> int:
    rclpy.init(args=args)
    node = None
    try:
        node = GroundCommandNode()
        executor = MultiThreadedExecutor(num_threads=EXECUTOR_THREADS)
        executor.add_node(node)
        executor.spin()
    except ValueError as exc:  # config, scene graph, vocabulary, backend or key problems
        get_logger("ground_command").error(f"startup failed: {exc}")
        return 1
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
