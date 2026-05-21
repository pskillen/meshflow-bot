"""Tests for :mod:`src.packet_log`."""

from __future__ import annotations

from unittest.mock import patch

from src.packet_log import log_incoming_packet, log_packets_enabled
from src.radio.events import IncomingPacket


def test_log_packets_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LOG_PACKETS", raising=False)
    assert log_packets_enabled() is False


def test_log_packets_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LOG_PACKETS", "true")
    assert log_packets_enabled() is True


@patch("src.packet_log.logger")
def test_log_meshcore_packet(mock_logger, monkeypatch) -> None:
    monkeypatch.setenv("LOG_PACKETS", "true")
    log_incoming_packet(
        IncomingPacket(
            portnum="MC_CHANNEL_MSG_RECV",
            from_id="mc:channel:0:rx",
            to_id=None,
            channel=0,
            has_decoded=True,
            raw={
                "meshcore": True,
                "type": "channel_message",
                "payload": {"text": "hello mesh", "channel_idx": 0},
                "attributes": {},
            },
        )
    )
    mock_logger.info.assert_called_once()
    args = mock_logger.info.call_args[0]
    assert "channel_message" in " ".join(str(a) for a in args)


@patch("src.packet_log.logger")
def test_log_meshtastic_packet(mock_logger, monkeypatch) -> None:
    monkeypatch.setenv("LOG_PACKETS", "1")
    log_incoming_packet(
        IncomingPacket(
            portnum="TEXT_MESSAGE_APP",
            from_id="!aabbccdd",
            to_id="!11223344",
            channel=0,
            has_decoded=True,
            raw={
                "id": 99,
                "decoded": {
                    "portnum": "TEXT_MESSAGE_APP",
                    "text": "ping",
                },
            },
        )
    )
    mock_logger.info.assert_called_once()
    args = mock_logger.info.call_args[0]
    assert "TEXT_MESSAGE_APP" in " ".join(str(a) for a in args)


@patch("src.packet_log.logger")
def test_log_skipped_when_disabled(mock_logger, monkeypatch) -> None:
    monkeypatch.setenv("LOG_PACKETS", "false")
    log_incoming_packet(
        IncomingPacket(
            portnum="MC_ACK", from_id=None, to_id=None, raw={"meshcore": True}
        )
    )
    mock_logger.info.assert_not_called()
