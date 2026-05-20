"""Tests for :mod:`src.meshcore.translation`."""

from __future__ import annotations

import json
from pathlib import Path

from meshcore.events import Event, EventType
from src.meshcore.translation import event_to_incoming_packet

DOCS = Path(__file__).resolve().parents[2] / "docs" / "meshcore_packets"


def _load(name: str) -> dict:
    return json.loads((DOCS / name).read_text())


def test_rx_log_data_incoming_packet() -> None:
    dump = _load("rx_log_data/20260506_211139_847711.json")
    event = Event(EventType.RX_LOG_DATA, dump["payload"])
    packet = event_to_incoming_packet(event)
    assert packet is not None
    assert packet.raw["type"] == "rx_log_data"
    assert packet.raw["payload"]["payload_typename"] == "ADVERT"


def test_rx_log_data_fixture_serialises_with_coords() -> None:
    """Full path: translation envelope -> serializer (existing test coverage)."""
    from src.meshcore.serializers import MeshCorePacketSerializer

    dump = _load("rx_log_data/20260506_211139_847711.json")
    event = Event(EventType.RX_LOG_DATA, dump["payload"])
    packet = event_to_incoming_packet(event)
    assert packet is not None
    out = MeshCorePacketSerializer().serialise_raw_packet(packet.raw)
    assert out["event_type"] == "rx_log_data"
    assert out["payload_type"] == "advert"
    assert out["adv_lat"] == 55.99578
