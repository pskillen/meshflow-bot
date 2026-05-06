"""Tests for :mod:`src.meshcore.radio` dispatch path."""

from __future__ import annotations

from pathlib import Path

import pytest
from meshcore.events import Event, EventType

from src.meshcore.radio import MeshCoreRadio
from src.radio.events import IncomingPacket, IncomingTextMessage, NodeUpdate
from src.radio.interface import RadioHandlers


def test_meshcore_radio_dispatch_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MESHCORE_DUMP_ENABLED", "true")
    received: list[tuple[str, object]] = []

    def on_packet(p: IncomingPacket) -> None:
        received.append(("packet", p))

    def on_text(t: IncomingTextMessage) -> None:
        received.append(("text", t))

    def on_node(u: NodeUpdate) -> None:
        received.append(("node", u))

    radio = MeshCoreRadio(serial_device="/dev/null-not-used", data_dir=tmp_path)
    radio.set_handlers(
        RadioHandlers(
            on_packet=on_packet,
            on_text_message=on_text,
            on_node_update=on_node,
        )
    )
    radio._local_node_id = "mc:testlocal12"

    ev = Event(
        EventType.CONTACT_MSG_RECV,
        {
            "type": "PRIV",
            "pubkey_prefix": "aabbccddeeff",
            "text": "!ping",
        },
        {},
    )
    radio.dispatch_meshcore_event_for_tests(ev)

    assert (tmp_path / "meshcore_packets" / "contact_message").exists()
    json_files = list((tmp_path / "meshcore_packets" / "contact_message").glob("*.json"))
    assert len(json_files) == 1
    kinds = [k for k, _ in received]
    assert "packet" in kinds
    assert "text" in kinds


def test_meshcore_radio_invalid_transport_raises() -> None:
    with pytest.raises(ValueError):
        MeshCoreRadio(serial_device=None, ble_address=None)
    with pytest.raises(ValueError):
        MeshCoreRadio(serial_device="/dev/ttyUSB0", ble_address="AA:BB:CC:DD:EE:FF")
