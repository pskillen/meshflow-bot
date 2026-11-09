"""Meshtastic-shaped api serializers and the :class:`PacketSerializer` adapter.

The model serializers (``MeshNodeSerializer``, ``PositionSerializer``,
``DeviceMetricsSerializer``) translate the bot's internal :class:`MeshNode`
into the JSON shape meshflow-api expects today (which is Meshtastic-shaped).
:class:`MeshtasticPacketSerializer` is the entry point used by
:class:`~src.api.StorageAPI.StorageAPIWrapper` — it just defers to those
serializers and adds raw-packet sanitisation.
"""

from __future__ import annotations

import base64
import datetime
import logging
import time
from abc import ABC
from typing import Any, Callable, Optional

from src.api.packet_serializer import PacketSerializer
from src.data_classes import MeshNode
from src.meshtastic.wire_fields import (
    ACK_PROOF_NAMES,
    is_firmware_2_8_or_later,
    read_signing_fields,
)

logger = logging.getLogger(__name__)


def _meshtastic_location_source_for_api(source: str | None) -> str:
    """Map bot/Meshtastic location source strings to meshflow-api labels."""
    if not source:
        return "UNSET"
    if source in ("LOC_UNSET", "LOC_UNKNOWN"):
        return "UNSET"
    return source


class AbstractModelSerializer(ABC):
    @classmethod
    def to_api_dict(cls, model) -> dict:
        raise NotImplementedError

    @classmethod
    def from_api_dict(cls, model_data: dict):
        raise NotImplementedError

    @staticmethod
    def date_to_api(date: datetime.datetime) -> str:
        return date.strftime("%Y-%m-%d %H:%M:%SZ")

    @staticmethod
    def date_from_api(date_str: str) -> datetime.datetime:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%SZ")


class PositionSerializer(AbstractModelSerializer):
    @classmethod
    def to_api_dict(cls, position: MeshNode.Position) -> dict:
        return {
            "logged_time": cls.date_to_api(
                position.logged_time
            ),  # api v1 compatibility
            "reported_time": cls.date_to_api(
                position.reported_time
            ),  # api v2 compatibility
            "latitude": position.latitude,
            "longitude": position.longitude,
            "altitude": position.altitude,
            "meshtastic_location_source": _meshtastic_location_source_for_api(
                position.location_source
            ),
        }

    @classmethod
    def from_api_dict(cls, position_data: dict) -> MeshNode.Position:
        return MeshNode.Position(
            logged_time=cls.date_from_api(position_data["logged_time"]),
            reported_time=cls.date_from_api(position_data["reported_time"]),
            latitude=position_data["latitude"],
            longitude=position_data["longitude"],
            altitude=position_data["altitude"],
            location_source=position_data.get(
                "meshtastic_location_source",
                position_data.get("location_source", ""),
            ),
        )


class DeviceMetricsSerializer(AbstractModelSerializer):
    @classmethod
    def to_api_dict(cls, device_metrics: MeshNode.DeviceMetrics) -> dict:
        return {
            "logged_time": cls.date_to_api(
                device_metrics.logged_time
            ),  # api v1 compatibility
            "reported_time": cls.date_to_api(
                device_metrics.logged_time
            ),  # api v2 compatibility
            "battery_level": device_metrics.battery_level,
            "voltage": device_metrics.voltage,
            "meshtastic_channel_utilization": device_metrics.channel_utilization or 0.0,
            "meshtastic_air_util_tx": device_metrics.air_util_tx or 0.0,
            "uptime_seconds": device_metrics.uptime_seconds,
        }

    @classmethod
    def from_api_dict(cls, device_metrics_data: dict) -> MeshNode.DeviceMetrics:
        return MeshNode.DeviceMetrics(
            logged_time=cls.date_from_api(device_metrics_data["logged_time"]),
            battery_level=device_metrics_data["battery_level"],
            voltage=device_metrics_data["voltage"],
            channel_utilization=device_metrics_data.get(
                "meshtastic_channel_utilization",
                device_metrics_data.get("channel_utilization", 0.0),
            ),
            air_util_tx=device_metrics_data.get(
                "meshtastic_air_util_tx",
                device_metrics_data.get("air_util_tx", 0.0),
            ),
            uptime_seconds=device_metrics_data["uptime_seconds"],
        )


class MeshNodeSerializer(AbstractModelSerializer):
    # BE CAREFUL: The API node/user models do not match the local node/user models (same fields, moved around)

    @classmethod
    def to_api_dict(cls, node: MeshNode) -> dict:
        node_data = {
            "id": node.user.id,
            "macaddr": node.user.macaddr,
            "hw_model": node.user.hw_model,
            "public_key": node.user.public_key,
            "user": {
                "long_name": node.user.long_name,
                "short_name": node.user.short_name,
            },
        }

        # NodeDB lastHeard lets the API tell a stale uploaded name from a fresh one
        if node.last_heard:
            node_data["last_heard"] = node.last_heard.astimezone(
                datetime.timezone.utc
            ).isoformat()

        # only log a position if it's actually set
        if node.position and not (
            node.position.latitude == 0
            and node.position.longitude == 0
            and node.position.altitude == 0
        ):
            node_data["position"] = PositionSerializer.to_api_dict(node.position)

        if node.device_metrics:
            node_data["device_metrics"] = DeviceMetricsSerializer.to_api_dict(
                node.device_metrics
            )

        return node_data

    @classmethod
    def from_api_dict(cls, node_data: dict) -> MeshNode:
        user_data = node_data["user"]
        user = MeshNode.User(
            node_id=node_data["id"],
            macaddr=node_data["macaddr"],
            hw_model=node_data["hw_model"],
            public_key=node_data["public_key"],
            long_name=user_data["long_name"],
            short_name=user_data["short_name"],
        )

        position_data = node_data.get("position")
        position = None
        if position_data:
            position = PositionSerializer.from_api_dict(position_data)

        device_metrics_data = node_data.get("device_metrics")
        device_metrics = None
        if device_metrics_data:
            device_metrics = DeviceMetricsSerializer.from_api_dict(device_metrics_data)

        node = MeshNode()
        node.user = user
        node.position = position
        node.device_metrics = device_metrics

        return node


def _sanitise_raw_packet(data: Any) -> Any:
    """Recursively scrub bytes (-> base64) and drop the ``raw`` protobuf
    field from a Meshtastic packet dict before upload."""
    if isinstance(data, dict):
        cleaned = {k: v for k, v in data.items() if k != "raw"}
        return {key: _sanitise_raw_packet(value) for key, value in cleaned.items()}
    if isinstance(data, list):
        return [_sanitise_raw_packet(item) for item in data]
    if isinstance(data, bytes):
        return base64.b64encode(data).decode("utf-8")
    return data


class MeshtasticPacketSerializer(PacketSerializer):
    """Meshtastic-shaped concrete :class:`PacketSerializer`.

    ``firmware_version`` is a callable returning the feeder's firmware string
    (or None); it decides whether "not signed" can be reported as ``false``.
    """

    def __init__(
        self, firmware_version: Optional[Callable[[], Optional[str]]] = None
    ) -> None:
        self._firmware_version = firmware_version

    def _add_signing_fields(self, cleaned: dict, raw_proto: Any) -> None:
        """Add the 2.8 signing fields (read from the raw protobuf, since lib
        2.7 drops them) to the ingest body. Absent means unknown. Removed with
        the library bump (LB-1): a 2.8 library puts the keys in the dict."""
        if "xeddsaSigned" in cleaned:
            return
        fields = read_signing_fields(raw_proto)
        if fields.xeddsa_signed:
            cleaned["xeddsaSigned"] = True
        else:
            try:
                version = self._firmware_version() if self._firmware_version else None
            except Exception:  # noqa: BLE001
                version = None
            if is_firmware_2_8_or_later(version):
                cleaned["xeddsaSigned"] = False
        if fields.signature:
            decoded = cleaned.get("decoded")
            if isinstance(decoded, dict):
                decoded["xeddsaSignature"] = base64.b64encode(fields.signature).decode(
                    "ascii"
                )
        if fields.ack_proof_status:
            cleaned["ackProofStatus"] = ACK_PROOF_NAMES.get(
                fields.ack_proof_status, str(fields.ack_proof_status)
            )

    def serialise_raw_packet(self, packet: Any) -> dict:
        if not isinstance(packet, dict):
            raise TypeError(
                f"MeshtasticPacketSerializer expects a dict packet, got {type(packet).__name__}"
            )
        raw_proto = packet.get("raw")
        cleaned = _sanitise_raw_packet(packet)
        # Some fields are absent for nullish values; copy them off the protobuf
        # if we have it so the api receives a full record.
        if raw_proto is not None and "channel" not in cleaned:
            cleaned["channel"] = getattr(raw_proto, "channel", 0)
        # The API requires rxTime; locally generated packets (self telemetry)
        # may not carry one, so fall back to the host clock.
        if not cleaned.get("rxTime"):
            cleaned["rxTime"] = int(time.time())
        if raw_proto is not None:
            try:
                self._add_signing_fields(cleaned, raw_proto)
            except Exception as exc:  # noqa: BLE001 - never stop an upload
                logger.warning("signing fields skipped: %s", exc)
        return cleaned

    def serialise_node(self, node: MeshNode) -> dict:
        return MeshNodeSerializer.to_api_dict(node)

    def deserialise_node(self, node_data: dict) -> MeshNode:
        return MeshNodeSerializer.from_api_dict(node_data)
