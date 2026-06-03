import time
import logging
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Lap:
    timestamp: float
    duration: float
    comment: Optional[str] = None


class Stopwatch:
    def __init__(self):
        self._start_time: Optional[float] = None
        self._laps: List[Lap] = []
        self._description: Optional[str] = None
        self._is_running: bool = False

    def start(self, description: Optional[str] = None) -> None:
        """Start the stopwatch with an optional description."""
        if self._is_running:
            logger.warning("Stopwatch is already running")
            return

        self._start_time = time.time()
        self._description = description
        self._is_running = True
        self._laps = []

        if description:
            logger.info(f"Stopwatch started: {description}")
        else:
            logger.info("Stopwatch started")

    def lap(self, comment: Optional[str] = None) -> float:
        """Record a lap time with an optional comment."""
        if not self._is_running:
            logger.warning("Stopwatch is not running")
            return 0.0

        current_time = time.time()
        duration = current_time - self._start_time
        self._laps.append(
            Lap(timestamp=current_time, duration=duration, comment=comment)
        )

        if comment:
            logger.info(f"Lap recorded: {comment} - {duration:.3f}s")
        else:
            logger.info(f"Lap recorded: {duration:.3f}s")

        return duration

    def stop(self) -> float:
        """Stop the stopwatch and return the total duration."""
        if not self._is_running:
            logger.warning("Stopwatch is not running")
            return 0.0

        total_duration = time.time() - self._start_time
        self._is_running = False

        if self._description:
            logger.info(
                f"Stopwatch stopped: {self._description} - Total: {total_duration:.3f}s"
            )
        else:
            logger.info(f"Stopwatch stopped - Total: {total_duration:.3f}s")

        return total_duration

    def get_summary(self) -> str:
        """Get a formatted summary of all laps and total duration."""
        if not self._laps:
            return "No laps recorded"

        summary = []
        if self._description:
            summary.append(f"Stopwatch: {self._description}")

        for i, lap in enumerate(self._laps, 1):
            lap_info = f"Lap {i}: {lap.duration:.3f}s"
            if lap.comment:
                lap_info += f" - {lap.comment}"
            summary.append(lap_info)

        if not self._is_running and self._laps:
            total_duration = self._laps[-1].duration
            summary.append(f"Total duration: {total_duration:.3f}s")

        return "\n".join(summary)

    def reset(self) -> None:
        """Reset the stopwatch to its initial state."""
        self._start_time = None
        self._laps = []
        self._description = None
        self._is_running = False
        logger.info("Stopwatch reset")
