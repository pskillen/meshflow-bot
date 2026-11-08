"""Detect Meshtastic 2.8's connect-time NodeDB replay.

After ``config_complete_id`` a 2.8 radio sends the client one synthetic
POSITION_APP, TELEMETRY_APP and NODE_STATUS_APP packet per NodeDB node, built
from stored history (``rx_time`` = the node's ``last_heard``). They look like
received packets but were not received now. The 2.8 proto marks them by
leaving ``rx_rssi`` unset; real LoRa receptions always carry a negative RSSI (MQTT-downlinked packets
have none either, so they are excluded via ``viaMqtt``/``transportMechanism``).

Detection rule (lib 2.7.11 dict): all of these must hold: ``from`` is not our
node number, the packet did not arrive via MQTT, the dict has no ``rxRssi``
key, ``transportMechanism`` is ``TRANSPORT_LORA`` and ``priority`` is
``BACKGROUND``. Across all four hardware captures this matches every one of
the 156 replayed packets and no live packet. A 2.8 library exposes
``has_rx_rssi`` explicitly; swap :func:`_has_rx_rssi` for that and nothing
else changes.

``REPLAYED_PACKETS`` = ``drop`` (default) | ``flag`` | ``pass`` decides what the
bot does with them.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MODE_DROP = "drop"
MODE_FLAG = "flag"
MODE_PASS = "pass"
MODES = (MODE_DROP, MODE_FLAG, MODE_PASS)
DEFAULT_MODE = MODE_DROP

REPLAY_COUNTER_NAME = "radio.replayed_packets"
SUMMARY_QUIET_SECONDS = 30.0
"""Seconds without a replayed packet before the connect summary is logged."""


def parse_mode(value: Optional[str]) -> str:
    """Parse ``REPLAYED_PACKETS``; unset or unknown falls back to ``drop``."""
    text = (value or "").strip().lower()
    if not text:
        return DEFAULT_MODE
    if text not in MODES:
        logger.warning(
            "REPLAYED_PACKETS=%r is not one of %s; using %r",
            value,
            "/".join(MODES),
            DEFAULT_MODE,
        )
        return DEFAULT_MODE
    return text


def _has_rx_rssi(packet: dict) -> bool:
    # lib 2.7.11 omits the key when the field is unset. With a 2.8 lib use the
    # explicit presence flag instead: packet["raw"].HasField("rx_rssi").
    return "rxRssi" in packet


def _via_mqtt(packet: dict) -> bool:
    # MQTT-downlinked packets are live but, like replays, carry no RSSI.
    if packet.get("viaMqtt"):
        return True
    return "MQTT" in str(packet.get("transportMechanism") or "").upper()


def is_replayed(packet: dict, local_nodenum: Optional[int]) -> bool:
    """True if *packet* is a connect-time replay rather than a live reception.

    Requires every one of: not from our node, not via MQTT, no RSSI,
    ``transportMechanism`` ``TRANSPORT_LORA`` and ``priority`` ``BACKGROUND``.
    With the local node number unknown nothing is classified as a replay."""
    if local_nodenum is None or not isinstance(packet, dict):
        return False
    if packet.get("from") == local_nodenum:
        return False
    if _via_mqtt(packet):
        return False
    if _has_rx_rssi(packet):
        return False
    if packet.get("transportMechanism") != "TRANSPORT_LORA":
        return False
    return packet.get("priority") == "BACKGROUND"


class ReplaySummary:
    """Counts replayed packets per connect and logs one INFO line per connect.

    The burst has no end marker, so the line is logged once no replayed packet
    has arrived for ``quiet_seconds`` (or when the next connect starts)."""

    def __init__(
        self,
        mode: str = DEFAULT_MODE,
        *,
        counter=None,
        quiet_seconds: float = SUMMARY_QUIET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        use_timer: bool = True,
    ) -> None:
        self.mode = mode
        self._counter = counter
        self._quiet = quiet_seconds
        self._clock = clock
        self._use_timer = use_timer
        self._lock = threading.Lock()
        self._connected_at: Optional[float] = None
        self._last_at: Optional[float] = None
        self._count = 0
        self._timer: Optional[threading.Timer] = None
        self._logged = False

    def start_connect(self) -> None:
        self.flush()
        with self._lock:
            self._logged = False
            self._connected_at = self._clock()

    def record(self) -> None:
        with self._lock:
            now = self._clock()
            if self._connected_at is None:
                self._connected_at = now
            self._count += 1
            self._last_at = now
            if self._use_timer:
                self._cancel_timer()
                self._timer = threading.Timer(self._quiet, self.flush)
                self._timer.daemon = True
                self._timer.start()
        if self._counter is not None:
            self._counter.increment(REPLAY_COUNTER_NAME)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def flush(self) -> Optional[str]:
        """Log the pending summary, if any; returns the line (for tests)."""
        with self._lock:
            self._cancel_timer()
            if not self._count:
                return None
            window = (self._last_at or 0) - (self._connected_at or 0)
            count, self._count = self._count, 0
            self._last_at = None
            if self._logged:
                # Late stragglers after the line: one line per connect.
                return None
            self._logged = True
        verb = {MODE_DROP: "dropped", MODE_FLAG: "flagged"}.get(self.mode, "passed")
        line = f"replayed packets: {count} {verb} in the first {window:.0f} s"
        logger.info(line)
        return line
