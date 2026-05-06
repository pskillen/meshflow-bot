"""MeshCore :class:`~src.api.packet_serializer.PacketSerializer` (stub for Phase 0.3)."""

from __future__ import annotations

from typing import Any

from src.api.packet_serializer import PacketSerializer
from src.data_classes import MeshNode


class MeshCorePacketSerializer(PacketSerializer):
    """Capture-only placeholder; Phase 1 wires :meth:`serialise_raw_packet`."""

    def serialise_raw_packet(self, packet: Any) -> dict:
        raise NotImplementedError(
            "MeshCorePacketSerializer.serialise_raw_packet is not implemented until Phase 1"
        )

    def serialise_node(self, node: MeshNode) -> dict:
        raise NotImplementedError(
            "MeshCorePacketSerializer.serialise_node is not implemented until Phase 1"
        )

    def deserialise_node(self, node_data: dict) -> MeshNode:
        raise NotImplementedError(
            "MeshCorePacketSerializer.deserialise_node is not implemented until Phase 1"
        )
