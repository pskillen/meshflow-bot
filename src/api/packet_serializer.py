"""Protocol-agnostic interface for shaping packets on their way to meshflow-api.

The bot uploads two kinds of payloads via :class:`StorageAPIWrapper`:

1. raw packets (received off the air), shaped by :meth:`PacketSerializer.serialise_raw_packet`
2. node objects, shaped by :meth:`PacketSerializer.serialise_node` /
   :meth:`PacketSerializer.deserialise_node`

The Meshtastic-shaped concrete implementation lives in
:mod:`src.meshtastic.serializers`. A future MeshCore implementation slots in
behind the same interface without touching ``StorageAPIWrapper``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.data_classes import MeshNode


class PacketSerializer(ABC):
    """Translates between the bot's domain objects and meshflow-api JSON."""

    @abstractmethod
    def serialise_raw_packet(self, packet: Any) -> dict:
        """Convert a protocol-native received packet into an api-shaped dict."""

    @abstractmethod
    def serialise_node(self, node: MeshNode) -> dict:
        """Convert a :class:`MeshNode` into an api-shaped dict."""

    @abstractmethod
    def deserialise_node(self, node_data: dict) -> MeshNode:
        """Inverse of :meth:`serialise_node`."""
