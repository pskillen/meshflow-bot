"""Tests for :mod:`src.meshcore.translation`."""

from __future__ import annotations

import json
from pathlib import Path

from meshcore.events import Event, EventType
from src.meshcore.translation import (
    event_to_incoming_packet,
    event_to_node_update,
    event_to_text_message,
    mc_id_from_full_pubkey,
    mc_id_from_prefix,
)

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


def test_mc_id_helpers() -> None:
    pk = "A" * 64
    assert mc_id_from_full_pubkey(pk) == f"mc:{pk.lower()}"
    assert mc_id_from_prefix("AABBCCDDEEFF") == "mc:p:aabbccddeeff"


def test_advertisement_incoming_packet() -> None:
    dump = _load("advertisement/20260506_220053_180858.json")
    event = Event(EventType.ADVERTISEMENT, dump["payload"])
    packet = event_to_incoming_packet(event)
    assert packet is not None
    assert packet.from_id.startswith("mc:")


def test_path_update_incoming_packet() -> None:
    dump = _load("path_update/20260506_205759_895381.json")
    event = Event(EventType.PATH_UPDATE, dump["payload"])
    packet = event_to_incoming_packet(event)
    assert packet is not None
    assert packet.portnum == "MC_PATH_UPDATE"


def test_messages_waiting_incoming_packet() -> None:
    dump = _load("messages_waiting/20260506_205758_540343.json")
    event = Event(EventType.MESSAGES_WAITING, dump["payload"])
    packet = event_to_incoming_packet(event)
    assert packet is not None
    assert packet.portnum == "MC_MESSAGES_WAITING"


def test_contact_message_text_dm() -> None:
    dump = _load("contact_messages/20260506_205758_541689.json")
    event = Event(EventType.CONTACT_MSG_RECV, dump["payload"])
    msg = event_to_text_message(event, local_node_id="mc:local")
    assert msg is not None
    assert msg.is_dm is True
    assert msg.from_id.startswith("mc:p:")


def test_channel_message_text_broadcast() -> None:
    dump = _load("channel_messages/20260507_094921_075978.json")
    event = Event(EventType.CHANNEL_MSG_RECV, dump["payload"])
    msg = event_to_text_message(event, local_node_id="mc:local")
    assert msg is not None
    assert msg.is_dm is False
    assert msg.to_id.startswith("mc:channel:")


def test_contact_message_missing_prefix_returns_none() -> None:
    event = Event(EventType.CONTACT_MSG_RECV, {"type": "PRIV", "text": "hi"})
    assert event_to_text_message(event, local_node_id="mc:local") is None


def test_advertisement_node_update() -> None:
    dump = _load("advertisement/20260506_220053_180858.json")
    event = Event(EventType.ADVERTISEMENT, dump["payload"])
    update = event_to_node_update(event)
    assert update is not None
    assert update.node.user.hw_model == "MESHCORE"


def test_self_info_incoming_packet() -> None:
    event = Event(
        EventType.SELF_INFO,
        {"public_key": "ab" * 32},
    )
    packet = event_to_incoming_packet(event)
    assert packet is not None
    assert packet.is_self_telemetry is True
    assert packet.from_id == mc_id_from_full_pubkey("ab" * 32)


def test_battery_and_ack_packets() -> None:
    batt = event_to_incoming_packet(Event(EventType.BATTERY, {"level": 50}))
    assert batt is not None
    assert batt.is_self_telemetry is True
    ack = event_to_incoming_packet(Event(EventType.ACK, {}))
    assert ack is not None
    assert ack.portnum == "MC_ACK"
