"""Tests for :mod:`src.meshcore.serializers`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data_classes import MeshNode
from src.meshcore.serializers import (MeshCorePacketSerializer,
                                      MeshCoreSkipUpload)

DOCS = Path(__file__).resolve().parents[2] / "docs" / "meshcore_packets"


def _load(name: str) -> dict:
    return json.loads((DOCS / name).read_text())


def test_serialise_advertisement() -> None:
    raw = {
        "meshcore": True,
        "type": "advertisement",
        "payload": _load("advertisement/20260506_211140_430432.json")["payload"],
        "attributes": {},
    }
    out = MeshCorePacketSerializer().serialise_raw_packet(raw)
    assert out["payload_type"] == "advert"
    assert (
        out["from_pubkey"]
        == "f3bcf18b78deee33596d29d49aa6891d30ac6e2c97e7e6a9b81907f1470afcfc"
    )


def test_serialise_rx_log_advert() -> None:
    dump = _load("rx_log_data/20260506_211139_847711.json")
    raw = {
        "meshcore": True,
        "type": "rx_log_data",
        "payload": dump["payload"],
        "attributes": dump.get("attributes", {}),
    }
    out = MeshCorePacketSerializer().serialise_raw_packet(raw)
    assert out["payload_type"] == "advert"
    assert out["adv_name"] == "WMF"
    assert out["adv_lat"] == pytest.approx(55.99578)


def test_serialise_channel_message() -> None:
    dump = _load("channel_messages/20260507_094921_075978.json")
    raw = {
        "meshcore": True,
        "type": "channel_message",
        "payload": dump["payload"],
        "attributes": {},
    }
    out = MeshCorePacketSerializer().serialise_raw_packet(raw)
    assert out["payload_type"] == "channel_text"
    assert "text" in out


def test_serialise_contact_message() -> None:
    dump = _load("contact_messages/20260506_205845_841593.json")
    raw = {
        "meshcore": True,
        "type": "contact_message",
        "payload": dump["payload"],
        "attributes": {},
    }
    out = MeshCorePacketSerializer().serialise_raw_packet(raw)
    assert out["payload_type"] == "contact_text"
    assert out["from_pubkey_prefix"] == "e563a2e933ce"


def test_skip_rx_log_text() -> None:
    dump = _load("rx_log_data/20260506_205845_837997.json")
    raw = {
        "meshcore": True,
        "type": "rx_log_data",
        "payload": dump["payload"],
        "attributes": {},
    }
    with pytest.raises(MeshCoreSkipUpload):
        MeshCorePacketSerializer().serialise_raw_packet(raw)


def test_node_methods_not_implemented() -> None:
    ser = MeshCorePacketSerializer()
    with pytest.raises(NotImplementedError):
        node = MeshNode()
        node.user = MeshNode.User()
        ser.serialise_node(node)
    with pytest.raises(NotImplementedError):
        ser.deserialise_node({})
