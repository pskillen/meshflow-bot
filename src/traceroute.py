"""
Traceroute command handling: send traceroute requests and upload TRACEROUTE_APP responses.
"""

import logging
import os
import threading
import time
from typing import TYPE_CHECKING

from meshtastic.protobuf import mesh_pb2, portnums_pb2

if TYPE_CHECKING:
    from src.bot import MeshtasticBot

logger = logging.getLogger(__name__)

# Firmware enforces ~30s minimum between traceroutes. We rate-limit client-side to avoid
# sending requests the radio will reject (no ROUTING_APP packet).
TR_MIN_INTERVAL_SEC = int(os.getenv("TR_MIN_INTERVAL_SEC", "30"))
_last_tr_time: float = 0
_tr_lock = threading.Lock()

TR_HOPS_LIMIT = int(os.getenv("TR_HOPS_LIMIT", '5'))
if TR_HOPS_LIMIT < 3:
    logger.warning(f"TR_HOPS_LIMIT is less than 3, traceroutes are likely to fail. Capping at 3.")
    TR_HOPS_LIMIT = 3
elif TR_HOPS_LIMIT < 5:
    logger.warning(f"TR_HOPS_LIMIT is less than 5, traceroutes are likely to fail")

if TR_HOPS_LIMIT > 7:
    logger.warning(f"TR_HOPS_LIMIT is greater than the Meshtastic limit of 7. Capping at 7.")
    TR_HOPS_LIMIT = 7

def on_traceroute_command(bot: "MeshtasticBot", target_node_id: int, channel_index: int = 0):
    """
    Send a traceroute request to the target node.

    Args:
        bot: The MeshtasticBot instance
        target_node_id: Target node ID (integer, e.g. 1623194643)
        channel_index: Channel index (default 0)
    """
    global _last_tr_time

    if not bot.interface or not bot.init_complete:
        logger.warning("Traceroute: bot not connected, skipping")
        return

    with _tr_lock:
        now = time.monotonic()
        elapsed = now - _last_tr_time
        if elapsed < TR_MIN_INTERVAL_SEC:
            logger.info(
                f"Traceroute: rate limited (target={target_node_id}, "
                f"{TR_MIN_INTERVAL_SEC - int(elapsed)}s remaining)"
            )
            return
        _last_tr_time = now

    try:
        # Use sendData directly instead of sendTraceRoute: sendTraceRoute blocks until response
        # (or timeout ~2min), causing a backlog when responses are slow/lost. TR responses
        # arrive via meshtastic.receive and are handled by bot.on_receive.
        r = mesh_pb2.RouteDiscovery()
        bot.interface.sendData(
            r,
            destinationId=target_node_id,
            portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
            wantResponse=True,
            channelIndex=channel_index,
            hopLimit=TR_HOPS_LIMIT,
        )
        logger.info(f"Traceroute: sent to target={target_node_id}")
    except Exception as e:
        logger.error(f"Traceroute: failed to send to {target_node_id}: {e}")


def setup_traceroute_handler(bot: "MeshtasticBot"):
    """
    Subscribe to TRACEROUTE_APP packets and upload them to storage APIs.

    Call this once when the bot is initialized. TRACEROUTE_APP packets
    received via meshtastic.receive are already passed to storage_apis in
    bot.on_receive, so no extra subscription is needed for upload.

    This function exists for any traceroute-specific setup (e.g. filtering
    or logging). The main packet flow is: receive -> on_receive -> storage_apis.
    """
    # TRACEROUTE_APP packets are handled by bot.on_receive which forwards
    # all packets to storage_apis. No additional subscription needed.
    # We could add a dedicated handler here if we needed traceroute-specific
    # logic (e.g. only upload TR packets, or different handling).
    pass
