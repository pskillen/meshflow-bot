"""One background thread that retries failed uploads, serially and in order.

A per-failure ``threading.Timer`` costs a thread (and an 8 MB stack on 32-bit
Pis) per failing node; a 200-node sync against a down API would start 200 at
once. This worker keeps a heap of ``(due, seq, key)`` and a dict holding only
the *latest* payload for each key, and sends one retry at a time with a short
gap between them.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_GAP_SECONDS = 0.1


class RetryWorker:
    def __init__(
        self,
        gap: float = DEFAULT_GAP_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._gap = gap
        self._clock = clock
        self._cond = threading.Condition()
        self._heap: list[tuple[float, int, str]] = []
        # key -> (seq, fn, payload, attempt): the latest pending retry only.
        self._entries: dict[str, tuple[int, Callable[[Any, int], Any], Any, int]] = {}
        self._generation: dict[str, int] = {}
        self._seq = itertools.count()
        self._thread: Optional[threading.Thread] = None
        self._stopped = False

    def begin(self, key: str) -> int:
        """A new call for ``key`` starts: drop its pending retry and return a
        generation token. A retry scheduled with an older token is refused,
        so a stale payload is never sent after a newer one."""
        with self._cond:
            self._entries.pop(key, None)
            gen = self._generation.get(key, 0) + 1
            self._generation[key] = gen
            return gen

    def schedule(
        self,
        key: str,
        gen: int,
        delay: float,
        fn: Callable[[Any, int], Any],
        payload: Any,
        attempt: int,
    ) -> bool:
        """Run ``fn(payload, attempt)`` after ``delay`` seconds. Returns
        ``False`` (and does nothing) if ``gen`` is no longer current or the
        worker is stopped."""
        with self._cond:
            if self._stopped or self._generation.get(key) != gen:
                return False
            seq = next(self._seq)
            self._entries[key] = (seq, fn, payload, attempt)
            heapq.heappush(self._heap, (self._clock() + delay, seq, key))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="storage-retry", daemon=True
                )
                self._thread.start()
            self._cond.notify()
            return True

    def pending(self) -> int:
        with self._cond:
            return len(self._entries)

    def stop(self) -> None:
        """Ask the thread to exit; never blocks."""
        with self._cond:
            self._stopped = True
            self._entries.clear()
            self._heap.clear()
            self._cond.notify_all()

    def _next_due(self) -> Optional[tuple[Callable[[Any, int], Any], Any, int]]:
        with self._cond:
            while not self._stopped:
                if not self._heap:
                    self._cond.wait()
                    continue
                due, seq, key = self._heap[0]
                entry = self._entries.get(key)
                if entry is None or entry[0] != seq:  # cancelled or replaced
                    heapq.heappop(self._heap)
                    continue
                wait = due - self._clock()
                if wait > 0:
                    self._cond.wait(wait)
                    continue
                heapq.heappop(self._heap)
                del self._entries[key]
                return entry[1], entry[2], entry[3]
        return None

    def _run(self) -> None:
        while True:
            item = self._next_due()
            if item is None:
                return
            fn, payload, attempt = item
            try:
                fn(payload, attempt)
            except Exception as exc:  # never let the worker die
                logger.exception("Retry failed unexpectedly: %s", exc)
            with self._cond:
                if self._stopped:
                    return
                end = self._clock() + self._gap
                while not self._stopped:
                    remaining = end - self._clock()
                    if remaining <= 0:
                        break
                    self._cond.wait(remaining)
