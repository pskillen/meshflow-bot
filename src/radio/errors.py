"""Error boundaries for radio callbacks, storage uploads, and command dispatch.

The bot must never die because a single packet, a flaky API call, or a buggy
command handler raised. Wrap every such site with :func:`safe_callback` (as a
decorator) or use :class:`ErrorCounter` to track how often each site fires.
"""

from __future__ import annotations

import functools
import logging
import threading
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RadioError(Exception):
    """Raised by a :class:`RadioInterface` for protocol-level problems
    (failed connect, send-while-disconnected, malformed event, …)."""


class ErrorCounter:
    """Simple thread-safe in-process counter, keyed by site name.

    A future commit can wire these to Prometheus or any other metric sink;
    today we only need them so error rates are inspectable.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def increment(self, name: str) -> int:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + 1
            return self._counts[name]

    def get(self, name: str) -> int:
        with self._lock:
            return self._counts.get(name, 0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


_global_counter = ErrorCounter()


def get_global_error_counter() -> ErrorCounter:
    """Return the process-wide :class:`ErrorCounter` used by the bot."""
    return _global_counter


def safe_callback(
    name: str,
    *,
    counter: ErrorCounter | None = None,
    log: logging.Logger | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T | None]]:
    """Decorator that swallows and logs exceptions raised by ``fn``.

    Returns ``None`` on failure and increments ``counter[name]``. Use this on
    every callback the radio invokes, every storage-upload site, and every
    command/responder dispatch — the loop must keep running even when one
    handler explodes.
    """

    target_counter = counter if counter is not None else _global_counter
    target_log = log if log is not None else logger

    def decorator(fn: Callable[..., T]) -> Callable[..., T | None]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                target_counter.increment(name)
                target_log.exception("safe_callback %s raised: %s", name, exc)
                return None

        return wrapper

    return decorator


def call_safely(
    name: str,
    fn: Callable[..., T],
    *args,
    counter: ErrorCounter | None = None,
    log: logging.Logger | None = None,
    **kwargs,
) -> T | None:
    """Inline form of :func:`safe_callback` for one-shot invocations.

    Useful when you cannot decorate the call site (e.g. iterating over a list
    of handlers and invoking each, or wrapping a third-party callback).
    """

    target_counter = counter if counter is not None else _global_counter
    target_log = log if log is not None else logger
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        target_counter.increment(name)
        target_log.exception("call_safely %s raised: %s", name, exc)
        return None
