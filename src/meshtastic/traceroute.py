"""Meshtastic-specific traceroute / route-discovery.

Exposes :func:`send_traceroute` which the :class:`MeshtasticRadio` adapter
calls from its ``send_traceroute`` method. We use ``sendData`` directly
(not ``sendTraceRoute``) because the latter blocks until the response or a
~2 minute timeout, which causes a backlog when responses are slow or lost.
Responses come back via the regular ``meshtastic.receive`` pubsub topic and
are forwarded to storage by the bot just like any other packet.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from meshtastic.protobuf import mesh_pb2, portnums_pb2

logger = logging.getLogger(__name__)

# Firmware enforces ~30s minimum between traceroutes. Rate-limit client-side
# to avoid sending requests the radio will silently reject.
TR_MIN_INTERVAL_SEC = int(os.getenv("TR_MIN_INTERVAL_SEC", "30"))
_last_tr_time: float = 0
_tr_lock = threading.Lock()

TR_HOPS_LIMIT = int(os.getenv("TR_HOPS_LIMIT", "5"))
if TR_HOPS_LIMIT < 3:
    logger.warning("TR_HOPS_LIMIT is less than 3, traceroutes are likely to fail. Capping at 3.")
    TR_HOPS_LIMIT = 3
elif TR_HOPS_LIMIT < 5:
    logger.warning("TR_HOPS_LIMIT is less than 5, traceroutes are likely to fail")

if TR_HOPS_LIMIT > 7:
    logger.warning("TR_HOPS_LIMIT is greater than the Meshtastic limit of 7. Capping at 7.")
    TR_HOPS_LIMIT = 7


def send_traceroute(interface, target_node_id: int, channel_index: int = 0) -> None:
    """Send a traceroute (RouteDiscovery) request via a Meshtastic interface.

    Rate-limited per :data:`TR_MIN_INTERVAL_SEC`. ``interface`` must be an
    instance of (or compatible with) ``meshtastic.tcp_interface.TCPInterface``.
    """
    global _last_tr_time

    with _tr_lock:
        now = time.monotonic()
        elapsed = now - _last_tr_time
        if elapsed < TR_MIN_INTERVAL_SEC:
            logger.info(
                "Traceroute: rate limited (target=%s, %ss remaining)",
                target_node_id,
                TR_MIN_INTERVAL_SEC - int(elapsed),
            )
            return
        _last_tr_time = now

    try:
        interface.sendData(
            mesh_pb2.RouteDiscovery(),
            destinationId=target_node_id,
            portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
            wantResponse=True,
            channelIndex=channel_index,
            hopLimit=TR_HOPS_LIMIT,
        )
        logger.info("Traceroute: sent to target=%s", target_node_id)
    except Exception as exc:
        logger.error("Traceroute: failed to send to %s: %s", target_node_id, exc)
