"""MeshCore :class:`~src.api.packet_serializer.PacketSerializer` for API ingest."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.api.packet_serializer import PacketSerializer
from src.data_classes import MeshNode

logger = logging.getLogger(__name__)

UPLOADABLE_PAYLOAD_TYPES = frozenset({"advert", "channel_text", "contact_text"})


def _json_safe(value: Any) -> Any:
    """Recursively coerce meshcore event payloads to JSON-serialisable values."""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class MeshCoreSkipUpload(Exception):
    """Raised when a frame should not be uploaded (capture-only path)."""


def _normalise_envelope(packet: Any) -> dict[str, Any]:
    """Accept bot ``_raw_envelope`` or Phase 0.4 dump JSON."""
    if not isinstance(packet, dict):
        raise ValueError("MeshCore packet must be a dict envelope")
    if packet.get("meshcore"):
        return {
            "event_type": packet.get("type") or packet.get("event_type", ""),
            "payload": packet.get("payload") or {},
            "attributes": packet.get("attributes") or {},
        }
    if packet.get("protocol") == "meshcore":
        return {
            "event_type": packet.get("event_type", ""),
            "payload": packet.get("payload") or {},
            "attributes": packet.get("attributes") or {},
        }
    raise ValueError("Not a MeshCore envelope")


def _rx_time_from_payload(payload: dict, attributes: dict) -> float:
    for key in ("recv_time", "sender_timestamp"):
        if key in payload:
            return float(payload[key])
        if key in attributes:
            return float(attributes[key])
    return datetime.now(timezone.utc).timestamp()


def _path_hashes(payload: dict) -> list[str] | None:
    path = payload.get("path")
    if not path:
        return None
    if isinstance(path, list):
        return [str(p) for p in path]
    if isinstance(path, str) and path:
        # path may be concatenated hex pairs
        size = int(payload.get("path_hash_size", 2) or 2)
        return [
            path[i : i + size * 2]
            for i in range(0, len(path), size * 2)
            if path[i : i + size * 2]
        ]
    return None


def _build_from_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    event_type = str(envelope.get("event_type", "")).lower()
    payload = envelope.get("payload") or {}
    attributes = envelope.get("attributes") or {}

    path_hash_size = payload.get("path_hash_size")
    if path_hash_size is None:
        path_hash_size = 2
    path_hash_mode = payload.get("path_hash_mode")

    base: dict[str, Any] = {
        "event_type": event_type,
        "rx_time": _rx_time_from_payload(payload, attributes),
        "rx_rssi": payload.get("rssi"),
        "rx_snr": payload.get("snr"),
        "route_typename": payload.get("route_typename"),
        "path_hashes": _path_hashes(payload),
        "path_hash_size": int(path_hash_size) if path_hash_size is not None else None,
        "path_hash_mode": int(path_hash_mode) if path_hash_mode is not None else None,
        "pkt_hash": payload.get("pkt_hash"),
        "raw": _json_safe(envelope),
    }

    if event_type == "advertisement":
        pubkey = str(payload.get("public_key", "")).lower()
        return {
            **base,
            "payload_type": "advert",
            "from_pubkey": pubkey or None,
            "from_pubkey_prefix": pubkey[:12] if pubkey else None,
        }

    if event_type == "contact_message":
        prefix = str(payload.get("pubkey_prefix", "")).lower()
        return {
            **base,
            "payload_type": "contact_text",
            "from_pubkey_prefix": prefix or None,
            "to_pubkey_prefix": None,
            "channel_idx": int(payload.get("channel_idx", 0)),
            "text": str(payload.get("text", "")),
        }

    if event_type == "channel_message":
        return {
            **base,
            "payload_type": "channel_text",
            "from_pubkey": None,
            "from_pubkey_prefix": None,
            "channel_idx": int(payload.get("channel_idx", 0)),
            "text": str(payload.get("text", "")),
        }

    if event_type == "rx_log_data":
        typename = str(payload.get("payload_typename", "")).upper()
        if typename == "ADVERT":
            pubkey = str(payload.get("adv_key", "")).lower()
            return {
                **base,
                "payload_type": "advert",
                "from_pubkey": pubkey or None,
                "from_pubkey_prefix": pubkey[:12] if pubkey else None,
                "adv_name": payload.get("adv_name"),
                "adv_lat": payload.get("adv_lat"),
                "adv_lon": payload.get("adv_lon"),
            }
        raise MeshCoreSkipUpload(f"rx_log_data {typename} not uploaded in Phase 1")

    raise MeshCoreSkipUpload(f"event_type {event_type!r} not uploaded in Phase 1")


class MeshCorePacketSerializer(PacketSerializer):
    """Serialise MeshCore capture envelopes for ``POST /api/meshcore/packets/ingest/``."""

    def serialise_raw_packet(self, packet: Any) -> dict:
        envelope = _normalise_envelope(packet)
        result = _build_from_envelope(envelope)
        if result.get("payload_type") not in UPLOADABLE_PAYLOAD_TYPES:
            raise MeshCoreSkipUpload(
                f"payload_type {result.get('payload_type')!r} not uploadable"
            )
        return result

    def serialise_node(self, node: MeshNode) -> dict:
        raise NotImplementedError(
            "MeshCore node upsert is not implemented until a later phase"
        )

    def deserialise_node(self, node_data: dict) -> MeshNode:
        raise NotImplementedError(
            "MeshCore node upsert is not implemented until a later phase"
        )
