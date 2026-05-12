"""Translate :mod:`meshcore` events into bot :mod:`src.radio.events`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from meshcore.events import Event, EventType

from src.data_classes import MeshNode
from src.radio.events import IncomingPacket, IncomingTextMessage, NodeUpdate


def mc_id_from_full_pubkey(pubkey_hex: str) -> str:
    """Stable node id for a 32-byte (64-hex) MeshCore public key."""
    return f"mc:{pubkey_hex.lower()}"


def mc_id_from_prefix(pubkey_prefix_hex: str) -> str:
    """Node id for a 6-byte (12-hex) sender prefix from a message frame."""
    return f"mc:p:{pubkey_prefix_hex.lower()}"


def event_type_to_portnum(event_type: EventType) -> str:
    """Upper-case analogue of Meshtastic ``portnum`` for ``IncomingPacket``."""
    return f"MC_{event_type.name}"


def event_to_incoming_packet(event: Event) -> Optional[IncomingPacket]:
    """Build an :class:`IncomingPacket` for storage/dispatch, or ``None`` to skip."""
    et = event.type
    payload = event.payload if isinstance(event.payload, dict) else {}

    if et == EventType.CONTACT_MSG_RECV:
        from_id = None
        if "pubkey_prefix" in payload:
            from_id = mc_id_from_prefix(str(payload["pubkey_prefix"]))
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=from_id,
            to_id=None,
            channel=int(payload.get("channel_idx", 0)),
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.CHANNEL_MSG_RECV:
        ch = int(payload.get("channel_idx", 0))
        # Channel frames do not always include a sender pubkey; keep a stable placeholder.
        from_id = f"mc:channel:{ch}:rx"
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=from_id,
            to_id=None,
            channel=ch,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.ADVERTISEMENT:
        pk = str(payload.get("public_key", ""))
        from_id = mc_id_from_full_pubkey(pk) if pk else None
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=from_id,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.PATH_UPDATE:
        pk = str(payload.get("public_key", ""))
        from_id = mc_id_from_full_pubkey(pk) if pk else None
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=from_id,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.ACK:
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=None,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.BATTERY:
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=None,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=True,
            raw=_raw_envelope(event),
        )

    if et == EventType.RAW_DATA:
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=None,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.MESSAGES_WAITING:
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=None,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    if et == EventType.SELF_INFO:
        pk = str(payload.get("public_key", ""))
        from_id = mc_id_from_full_pubkey(pk) if pk else None
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=from_id,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=True,
            raw=_raw_envelope(event),
        )

    if et == EventType.DEVICE_INFO:
        return IncomingPacket(
            portnum=event_type_to_portnum(et),
            from_id=None,
            to_id=None,
            channel=0,
            has_decoded=True,
            is_self_telemetry=False,
            raw=_raw_envelope(event),
        )

    return None


def event_to_text_message(
    event: Event,
    *,
    local_node_id: Optional[str],
) -> Optional[IncomingTextMessage]:
    """Decoded text path for commands/responders."""
    if event.type not in (EventType.CONTACT_MSG_RECV, EventType.CHANNEL_MSG_RECV):
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    text = str(payload.get("text", ""))
    is_dm = payload.get("type") == "PRIV"
    ch = int(payload.get("channel_idx", 0))
    if event.type == EventType.CONTACT_MSG_RECV:
        prefix = str(payload.get("pubkey_prefix", ""))
        if not prefix:
            return None
        from_id = mc_id_from_prefix(prefix)
    else:
        from_id = f"mc:channel:{ch}:rx"
    if is_dm:
        to_id = local_node_id or ""
    else:
        to_id = f"mc:channel:{ch}"
    return IncomingTextMessage(
        text=text,
        from_id=from_id,
        to_id=to_id,
        channel=ch,
        message_id=0,
        hop_start=0,
        hop_limit=0,
        is_dm=is_dm,
        raw=_raw_envelope(event),
    )


def _contact_payload_to_node(contact: dict[str, Any]) -> MeshNode:
    """Build a :class:`MeshNode` from a MeshCore contact/advert dict."""
    pubkey = str(contact.get("public_key", "")).lower()
    node_id = mc_id_from_full_pubkey(pubkey) if pubkey else "mc:unknown"
    adv_name = str(contact.get("adv_name", "") or "").strip()
    long_name = adv_name or f"meshcore:{pubkey[:8]}"
    short_name = (adv_name[:4] if adv_name else pubkey[:4]) or "????"
    user = MeshNode.User(
        node_id=node_id,
        long_name=long_name,
        short_name=short_name,
        macaddr="",
        hw_model="MESHCORE",
        public_key=pubkey,
    )
    node = MeshNode()
    node.user = user
    node.position = None
    node.device_metrics = None
    node.is_favorite = False
    return node


def event_to_node_update(event: Event) -> Optional[NodeUpdate]:
    """Advert / contact events that should refresh the local node DB."""
    if event.type == EventType.ADVERTISEMENT:
        payload = event.payload if isinstance(event.payload, dict) else {}
        pk = str(payload.get("public_key", ""))
        if not pk:
            return None
        node = MeshNode()
        node.user = MeshNode.User(
            node_id=mc_id_from_full_pubkey(pk),
            long_name=f"meshcore:{pk[:8]}",
            short_name=pk[:4],
            macaddr="",
            hw_model="MESHCORE",
            public_key=pk.lower(),
        )
        node.position = None
        node.device_metrics = None
        node.is_favorite = False
        return NodeUpdate(
            node=node,
            last_heard=datetime.now(timezone.utc),
            raw=_raw_envelope(event),
        )

    if event.type in (EventType.NEW_CONTACT, EventType.NEXT_CONTACT):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if "public_key" not in payload:
            return None
        node = _contact_payload_to_node(payload)
        return NodeUpdate(
            node=node,
            last_heard=datetime.now(timezone.utc),
            raw=_raw_envelope(event),
        )

    return None


def _raw_envelope(event: Event) -> dict[str, Any]:
    """Opaque dict for the bot / dumps — not Meshtastic-shaped."""
    return {
        "meshcore": True,
        "type": event.type.value,
        "payload": event.payload,
        "attributes": dict(event.attributes) if event.attributes else {},
    }
