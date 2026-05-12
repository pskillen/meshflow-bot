"""Tests for :mod:`src.meshcore.translation`."""

from __future__ import annotations

from meshcore.events import Event, EventType

from src.meshcore.translation import (
    event_to_incoming_packet,
    event_to_node_update,
    event_to_text_message,
    mc_id_from_full_pubkey,
    mc_id_from_prefix,
)


def test_mc_ids() -> None:
    assert mc_id_from_prefix("AABBCCDDEEFF") == "mc:p:aabbccddeeff"
    assert mc_id_from_full_pubkey("AB" * 32) == "mc:" + "ab" * 32


def test_contact_message_to_packet_and_text() -> None:
    ev = Event(
        EventType.CONTACT_MSG_RECV,
        {
            "type": "PRIV",
            "pubkey_prefix": "112233445566",
            "text": "!help",
            "channel_idx": 0,
        },
        {"pubkey_prefix": "112233445566"},
    )
    pkt = event_to_incoming_packet(ev)
    assert pkt is not None
    assert pkt.portnum == "MC_CONTACT_MSG_RECV"
    assert pkt.from_id == "mc:p:112233445566"
    txt = event_to_text_message(ev, local_node_id="mc:localnode12")
    assert txt is not None
    assert txt.is_dm is True
    assert txt.to_id == "mc:localnode12"


def test_channel_message_placeholder_ids() -> None:
    ev = Event(
        EventType.CHANNEL_MSG_RECV,
        {
            "type": "CHAN",
            "channel_idx": 2,
            "text": "hello mesh",
        },
        {"channel_idx": 2},
    )
    pkt = event_to_incoming_packet(ev)
    assert pkt is not None
    assert pkt.from_id == "mc:channel:2:rx"
    txt = event_to_text_message(ev, local_node_id="mc:self")
    assert txt is not None
    assert txt.is_dm is False
    assert txt.from_id == "mc:channel:2:rx"


def test_advertisement_node_update() -> None:
    pk = "aa" * 32
    ev = Event(EventType.ADVERTISEMENT, {"public_key": pk})
    upd = event_to_node_update(ev)
    assert upd is not None
    assert upd.node.user.id == f"mc:{pk}"


def test_path_update_incoming_packet() -> None:
    pk = "bb" * 32
    ev = Event(EventType.PATH_UPDATE, {"public_key": pk})
    pkt = event_to_incoming_packet(ev)
    assert pkt is not None
    assert pkt.from_id == f"mc:{pk}"


def test_ack_battery_raw_messages_waiting() -> None:
    assert event_to_incoming_packet(Event(EventType.ACK, {"code": "01020304"})) is not None
    bat = event_to_incoming_packet(Event(EventType.BATTERY, {"level": 85}))
    assert bat is not None
    assert bat.is_self_telemetry is True
    assert event_to_incoming_packet(Event(EventType.RAW_DATA, {"SNR": 1.0, "RSSI": -90})) is not None
    assert event_to_incoming_packet(Event(EventType.MESSAGES_WAITING, {})) is not None


def test_self_info_and_device_info() -> None:
    pk = "cc" * 32
    self_ev = Event(EventType.SELF_INFO, {"public_key": pk})
    pkt = event_to_incoming_packet(self_ev)
    assert pkt is not None
    assert pkt.from_id == f"mc:{pk}"
    dev = event_to_incoming_packet(Event(EventType.DEVICE_INFO, {"model": "X"}))
    assert dev is not None
    assert dev.from_id is None


def test_new_contact_node_update() -> None:
    pk = "dd" * 32
    ev = Event(
        EventType.NEW_CONTACT,
        {
            "public_key": pk,
            "adv_name": "TestNode",
        },
    )
    upd = event_to_node_update(ev)
    assert upd is not None
    assert upd.node.user.long_name == "TestNode"


def test_unknown_event_returns_no_packet() -> None:
    assert event_to_incoming_packet(Event(EventType.ERROR, {"reason": "x"})) is None
