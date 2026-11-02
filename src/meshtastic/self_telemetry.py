"""Throttled upload of the feeder's own telemetry (Meshtastic only).

The connected radio reports its own telemetry to the client every few
seconds. Uploading each report spammed the API, so the bot used to drop them.
Firmware 2.8 turns broadcast telemetry off by default, which means other
feeders no longer hear a feeder's own telemetry over the air, so the bot has
to upload it itself, but throttled.

:class:`SelfTelemetryThrottle` keeps the newest sample per telemetry variant
(``deviceMetrics``, ``localStats``, ``powerMetrics``, ... including variants
added by newer firmware) and hands them out once per interval. The bot calls
:meth:`SelfTelemetryThrottle.flush` from a ``schedule`` job; each sample then
goes through the normal packet-report path. There is no server-side
throttling on purpose: it would still cost a request per sample.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 900
ENV_VAR = "SELF_TELEMETRY_UPLOAD_INTERVAL_SECONDS"

# Keys of a decoded ``telemetry`` dict that are not variants.
_NON_VARIANT_KEYS = frozenset({"time", "raw"})


def telemetry_variant(packet: dict) -> Optional[str]:
    """Return the telemetry variant name in ``packet`` (e.g. ``deviceMetrics``).

    Any dict-valued key other than ``time`` counts, so variants added by newer
    firmware are picked up without code changes. ``None`` if there is none.

    >>> telemetry_variant({"decoded": {"telemetry": {"time": 1, "localStats": {"numPacketsTx": 3}}}})
    'localStats'
    >>> telemetry_variant({"decoded": {"telemetry": {"time": 1}}}) is None
    True
    """
    telemetry = (packet.get("decoded") or {}).get("telemetry") or {}
    for key, value in telemetry.items():
        if key not in _NON_VARIANT_KEYS and isinstance(value, dict):
            return key
    return None


def interval_from_env(value: Optional[str] = None) -> int:
    """Parse the upload interval in seconds.

    Unset or invalid gives the default; negative is treated as 0 (disabled).

    >>> interval_from_env("0")
    0
    >>> interval_from_env("abc")
    900
    >>> interval_from_env("-5")
    0
    """
    raw = os.getenv(ENV_VAR) if value is None else value
    if raw is None or raw.strip() == "":
        return DEFAULT_INTERVAL_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "Invalid %s=%r; using default %s", ENV_VAR, raw, DEFAULT_INTERVAL_SECONDS
        )
        return DEFAULT_INTERVAL_SECONDS


class SelfTelemetryThrottle:
    """Latest unsent self-telemetry sample per variant."""

    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL_SECONDS):
        self.interval_seconds = interval_seconds
        self._pending: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.interval_seconds > 0

    def record(self, variant: str, packet: Any) -> None:
        """Remember ``packet`` as the newest sample of ``variant``."""
        if not self.enabled:
            return
        with self._lock:
            self._pending[variant] = packet

    def flush(self) -> list[Any]:
        """Return and clear the newest unsent sample of each variant."""
        with self._lock:
            packets = list(self._pending.values())
            self._pending.clear()
        return packets
