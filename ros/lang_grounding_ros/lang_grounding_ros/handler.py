"""One grounding call with a timeout; every outcome becomes response fields (D-130, D-131).

Plain Python only (no rclpy). `ground_fn(command)` is any callable that returns the dict of
`GroundOutcome.to_dict()`. The call runs in a worker thread, so a slow call neither blocks the
caller beyond the timeout nor takes down the node: an exception, a timeout or a malformed result
becomes a response with success False and a short error. A call that has timed out cannot be
killed; it finishes in the background (bounded by the backend's own timeout).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any

from .mapping import failure_fields, response_fields_from_outcome, short_error


class GroundingHandler:
    def __init__(
        self,
        ground_fn: Callable[[str], Mapping[str, Any]],
        timeout_s: float = 20.0,
        max_workers: int = 4,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._ground_fn = ground_fn
        self.timeout_s = timeout_s
        self._clock = clock
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ground")

    def handle(self, command: str) -> dict[str, Any]:
        """Response fields for one command. Never raises (except for KeyboardInterrupt etc.)."""
        start = self._clock()
        if not isinstance(command, str) or not command.strip():
            return failure_fields("empty command")
        try:
            future = self._pool.submit(self._ground_fn, command)
        except RuntimeError as exc:  # the pool was shut down
            return failure_fields(short_error(exc), self._clock() - start)
        done, _ = wait([future], timeout=self.timeout_s)
        if not done:
            future.cancel()  # only helps if the call has not started yet
            return failure_fields(
                f"timed out after {self.timeout_s:g} s", self._clock() - start)
        return self._collect(future, start)

    def _collect(self, future: Future, start: float) -> dict[str, Any]:
        try:
            outcome = future.result()
        except Exception as exc:  # the library raised: report it, do not crash
            return failure_fields(short_error(exc), self._clock() - start)
        try:
            return response_fields_from_outcome(outcome)
        except Exception as exc:  # the library result had an unexpected shape
            return failure_fields(
                "bad grounding result: " + short_error(exc), self._clock() - start)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
