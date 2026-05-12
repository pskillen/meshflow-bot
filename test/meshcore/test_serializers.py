"""Tests for :mod:`src.meshcore.serializers`."""

from __future__ import annotations

import pytest

from src.data_classes import MeshNode
from src.meshcore.serializers import MeshCorePacketSerializer


def test_meshcore_packet_serializer_stub() -> None:
    ser = MeshCorePacketSerializer()
    with pytest.raises(NotImplementedError):
        ser.serialise_raw_packet({})
    with pytest.raises(NotImplementedError):
        node = MeshNode()
        node.user = MeshNode.User()
        ser.serialise_node(node)
    with pytest.raises(NotImplementedError):
        ser.deserialise_node({})
