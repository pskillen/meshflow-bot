"""Translate Meshtastic packets into protocol-agnostic events.

The Meshtastic library hands us nested dicts shaped like ``MeshPacket``; the
bot only ever sees :mod:`src.radio.events`. Everything that knows the
``packet["decoded"]["text"]`` shape lives in this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.data_classes import MeshNode
from src.radio.events import IncomingPacket, IncomingTextMessage, NodeUpdate


def _portnum_key(packet: dict) -> str:
    portnum = packet.get("decoded", {}).get("portnum", "unknown")
    return str(portnum).upper()


def packet_to_incoming(packet: dict, *, local_node_id: Optional[str]) -> IncomingPacket:
    """Build an :class:`IncomingPacket` from a Meshtastic packet dict."""
    portnum_key = _portnum_key(packet)
    has_decoded = "decoded" in packet or "decrypted" in packet

    sender = packet.get("fromId")
    decoded = packet.get("decoded") or {}
    telemetry = decoded.get("telemetry") or {}
    is_self_telemetry = (
        local_node_id is not None
        and sender == local_node_id
        and portnum_key == "TELEMETRY_APP"
        and "deviceMetrics" in telemetry
    )

    return IncomingPacket(
        portnum=portnum_key,
        from_id=sender,
        to_id=packet.get("toId"),
        channel=packet.get("channel", 0) or 0,
        has_decoded=has_decoded,
        is_self_telemetry=is_self_telemetry,
        raw=packet,
    )


def packet_to_text_message(
    packet: dict, *, local_node_id: Optional[str]
) -> IncomingTextMessage:
    """Build an :class:`IncomingTextMessage` from a TEXT_MESSAGE_APP packet."""
    decoded = packet.get("decoded") or {}
    to_id = packet.get("toId", "")
    return IncomingTextMessage(
        text=decoded.get("text", ""),
        from_id=packet.get("fromId", ""),
        to_id=to_id,
        channel=packet.get("channel", 0) or 0,
        message_id=packet.get("id", 0) or 0,
        hop_start=packet.get("hopStart", 0) or 0,
        hop_limit=packet.get("hopLimit", 0) or 0,
        is_dm=local_node_id is not None and to_id == local_node_id,
        raw=packet,
    )


def node_dict_to_mesh_node(node_data: dict) -> MeshNode:
    """Build a :class:`MeshNode` from a Meshtastic-shaped node dict.

    Knows the Meshtastic camelCase keys (``longName``, ``hwModel``, …).
    Lives here, not on :class:`MeshNode`, because :class:`MeshNode` is the
    bot's protocol-agnostic domain model.
    """
    user_data = node_data.get("user", {}) or {}
    user = MeshNode.User(
        node_id=user_data.get("id", ""),
        long_name=user_data.get("longName", ""),
        short_name=user_data.get("shortName", ""),
        macaddr=user_data.get("macaddr", ""),
        hw_model=user_data.get("hwModel", ""),
        public_key=user_data.get("publicKey", ""),
    )

    position_data = node_data.get("position", {}) or {}
    position = MeshNode.Position(logged_time=datetime.now(timezone.utc))
    position.latitude = position_data.get("latitude", 0.0)
    position.longitude = position_data.get("longitude", 0.0)
    position.altitude = position_data.get("altitude", 0)
    position.reported_time = (
        datetime.fromtimestamp(position_data["time"], timezone.utc)
        if "time" in position_data
        else datetime.now(timezone.utc)
    )
    position.location_source = position_data.get("locationSource", "")

    metrics_data = node_data.get("deviceMetrics", {}) or {}
    metrics = MeshNode.DeviceMetrics(logged_time=datetime.now(timezone.utc))
    metrics.battery_level = metrics_data.get("batteryLevel", 0)
    metrics.voltage = metrics_data.get("voltage", 0.0)
    metrics.channel_utilization = metrics_data.get("channelUtilization", 0.0)
    metrics.air_util_tx = metrics_data.get("airUtilTx", 0.0)
    metrics.uptime_seconds = metrics_data.get("uptimeSeconds", 0)

    node = MeshNode()
    node.user = user
    node.position = position
    node.device_metrics = metrics
    node.is_favorite = node_data.get("isFavorite", False)
    return node


def node_dict_to_node_update(node_data: dict) -> Optional[NodeUpdate]:
    """Translate a Meshtastic node-update dict into a :class:`NodeUpdate`.

    Returns ``None`` when the node has no user payload (the bot ignores those,
    as it has no id to key on).
    """
    if node_data.get("user") is None:
        return None
    mesh_node = node_dict_to_mesh_node(node_data)
    last_heard_int = node_data.get("lastHeard", 0) or 0
    last_heard = datetime.fromtimestamp(last_heard_int, tz=timezone.utc)
    return NodeUpdate(node=mesh_node, last_heard=last_heard, raw=node_data)


def nodenum_to_id(nodenum: int) -> str:
    """Render an integer node-num as a canonical Meshtastic hex id (``!aabbccdd``)."""
    return f"!{nodenum:08x}"


def id_to_nodenum(node_id: str) -> int:
    """Parse a canonical Meshtastic hex id (``!aabbccdd``) into an int."""
    if node_id.startswith("!"):
        node_id = node_id[1:]
    return int(node_id, 16)


def packet_raw(packet: dict) -> Any:
    """Return the underlying protobuf packet stashed under ``raw``, if any."""
    return packet.get("raw")
