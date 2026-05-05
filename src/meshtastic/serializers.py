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
from abc import ABC
from typing import Any

from src.api.packet_serializer import PacketSerializer
from src.data_classes import MeshNode


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
            "logged_time": cls.date_to_api(position.logged_time),  # api v1 compatibility
            "reported_time": cls.date_to_api(position.reported_time),  # api v2 compatibility
            "latitude": position.latitude,
            "longitude": position.longitude,
            "altitude": position.altitude,
            "location_source": position.location_source or "LOC_UNKNOWN",
        }

    @classmethod
    def from_api_dict(cls, position_data: dict) -> MeshNode.Position:
        return MeshNode.Position(
            logged_time=cls.date_from_api(position_data['logged_time']),
            reported_time=cls.date_from_api(position_data['reported_time']),
            latitude=position_data['latitude'],
            longitude=position_data['longitude'],
            altitude=position_data['altitude'],
            location_source=position_data['location_source']
        )


class DeviceMetricsSerializer(AbstractModelSerializer):
    @classmethod
    def to_api_dict(cls, device_metrics: MeshNode.DeviceMetrics) -> dict:
        return {
            "logged_time": cls.date_to_api(device_metrics.logged_time),  # api v1 compatibility
            "reported_time": cls.date_to_api(device_metrics.logged_time),  # api v2 compatibility
            "battery_level": device_metrics.battery_level,
            "voltage": device_metrics.voltage,
            "channel_utilization": device_metrics.channel_utilization,
            "air_util_tx": device_metrics.air_util_tx,
            "uptime_seconds": device_metrics.uptime_seconds
        }

    @classmethod
    def from_api_dict(cls, device_metrics_data: dict) -> MeshNode.DeviceMetrics:
        return MeshNode.DeviceMetrics(
            logged_time=cls.date_from_api(device_metrics_data['logged_time']),
            battery_level=device_metrics_data['battery_level'],
            voltage=device_metrics_data['voltage'],
            channel_utilization=device_metrics_data['channel_utilization'],
            air_util_tx=device_metrics_data['air_util_tx'],
            uptime_seconds=device_metrics_data['uptime_seconds']
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
            'user': {
                "long_name": node.user.long_name,
                "short_name": node.user.short_name
            }
        }

        # only log a position if it's actually set
        if node.position and not \
                (node.position.latitude == 0 and node.position.longitude == 0 and node.position.altitude == 0):
            node_data['position'] = PositionSerializer.to_api_dict(node.position)

        if node.device_metrics:
            node_data['device_metrics'] = DeviceMetricsSerializer.to_api_dict(node.device_metrics)

        return node_data

    @classmethod
    def from_api_dict(cls, node_data: dict) -> MeshNode:
        user_data = node_data['user']
        user = MeshNode.User(
            node_id=node_data['id'],
            macaddr=node_data['macaddr'],
            hw_model=node_data['hw_model'],
            public_key=node_data['public_key'],
            long_name=user_data['long_name'],
            short_name=user_data['short_name']
        )

        position_data = node_data.get('position')
        position = None
        if position_data:
            position = PositionSerializer.from_api_dict(position_data)

        device_metrics_data = node_data.get('device_metrics')
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
    """Meshtastic-shaped concrete :class:`PacketSerializer`."""

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
        return cleaned

    def serialise_node(self, node: MeshNode) -> dict:
        return MeshNodeSerializer.to_api_dict(node)

    def deserialise_node(self, node_data: dict) -> MeshNode:
        return MeshNodeSerializer.from_api_dict(node_data)
