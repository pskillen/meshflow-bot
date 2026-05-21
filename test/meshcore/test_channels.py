"""Unit tests for MeshCore channel snapshot helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from meshcore.events import Event, EventType

from src.meshcore.channels import (
    _channel_entry_from_info,
    apply_device_channels,
    log_device_channels,
    read_device_channels,
    snapshot_sync_body,
)


def test_channel_entry_public():
    entry = _channel_entry_from_info(0, {"channel_name": "Public"})
    assert entry["mc_channel_type"] == "PUBLIC"
    assert entry["mc_hashtag"] is None


def test_channel_entry_hashtag():
    entry = _channel_entry_from_info(1, {"channel_name": "#galloway"})
    assert entry["mc_channel_type"] == "HASHTAG"
    assert entry["mc_hashtag"] == "galloway"


def test_log_device_channels(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    log_device_channels(
        [
            {"mc_channel_idx": 0, "name": "Public", "mc_channel_type": "PUBLIC"},
            {
                "mc_channel_idx": 1,
                "name": "galloway",
                "mc_channel_type": "HASHTAG",
                "mc_hashtag": "galloway",
            },
        ]
    )
    text = caplog.text
    assert "MeshCore device channels (2):" in text
    assert "Public" in text
    assert "galloway" in text


def test_log_device_channels_empty(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    log_device_channels([])
    assert "none configured" in caplog.text


def test_snapshot_sync_body():
    body = snapshot_sync_body(
        [{"mc_channel_idx": 0, "name": "X", "mc_channel_type": "PUBLIC"}]
    )
    assert "synced_at" in body
    assert len(body["channels"]) == 1


def test_channel_entry_empty_name_returns_none() -> None:
    assert _channel_entry_from_info(0, {"channel_name": "   "}) is None


def test_read_device_channels_logs_scan_when_empty(caplog) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    mc = MagicMock()
    mc.commands.get_channel = AsyncMock(
        return_value=Event(EventType.ERROR, {"reason": "not_found"}, {})
    )
    channels = asyncio.run(read_device_channels(mc, max_channels=2))
    assert channels == []
    assert "get_channel scan found 0 named channels" in caplog.text
    assert "[0] ERROR" in caplog.text


def test_read_device_channels_collects_public_and_skips_errors() -> None:
    mc = MagicMock()
    mc.commands.get_channel = AsyncMock(
        side_effect=[
            Event(EventType.ERROR, {}, {}),
            Event(EventType.CHANNEL_INFO, {"channel_name": "Public"}, {}),
            Event(EventType.CHANNEL_INFO, {"channel_name": ""}, {}),
            Event(EventType.ERROR, {}, {}),
        ]
    )
    channels = asyncio.run(read_device_channels(mc, max_channels=4))
    assert len(channels) == 1
    assert channels[0]["mc_channel_type"] == "PUBLIC"


def test_apply_device_channels_hashtag_and_error() -> None:
    mc = MagicMock()
    mc.commands.set_channel = AsyncMock(
        side_effect=[
            Event(EventType.CHANNEL_INFO, {}, {}),
            Event(EventType.ERROR, {"msg": "fail"}, {}),
        ]
    )
    asyncio.run(
        apply_device_channels(
            mc,
            [
                {
                    "mc_channel_idx": 1,
                    "name": "galloway",
                    "mc_channel_type": "HASHTAG",
                    "mc_hashtag": "galloway",
                },
                {"mc_channel_idx": 2, "name": "two", "mc_channel_type": "PUBLIC"},
            ],
        )
    )
    assert mc.commands.set_channel.await_count == 2
    first_call = mc.commands.set_channel.await_args_list[0]
    assert first_call[0] == (1, "#galloway")
