"""Unit tests for MeshCore channel snapshot helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from meshcore.events import Event, EventType
from src.meshcore.channels import (_channel_entry_from_info,
                                   apply_device_channels, log_device_channels,
                                   merge_channel_region_scopes,
                                   read_device_channels, snapshot_sync_body)


def test_channel_entry_public():
    entry = _channel_entry_from_info(0, {"channel_name": "Public"})
    assert entry["mc_channel_type"] == "PUBLIC"
    assert entry["region_scope"] is None


def test_channel_entry_hashtag():
    entry = _channel_entry_from_info(1, {"channel_name": "#galloway"})
    assert entry["mc_channel_type"] == "HASHTAG"
    assert entry["name"] == "galloway"
    assert entry["region_scope"] is None


def test_channel_entry_with_region_scope():
    entry = _channel_entry_from_info(
        1,
        {"channel_name": "#galloway", "scope_name": "Sample-West"},
    )
    assert entry["region_scope"] == "sample-west"


def test_merge_channel_region_scopes_from_apply_intent():
    device = [
        {
            "mc_channel_idx": 0,
            "name": "galloway",
            "mc_channel_type": "HASHTAG",
            "region_scope": None,
        },
    ]
    intent = [
        {
            "mc_channel_idx": 0,
            "name": "galloway",
            "mc_channel_type": "HASHTAG",
            "region_scope": "uk-wide",
        },
    ]
    merged = merge_channel_region_scopes(device, intent)
    assert merged[0]["region_scope"] == "uk-wide"


def test_merge_clears_scope_when_intent_null():
    device = [
        {
            "mc_channel_idx": 0,
            "name": "galloway",
            "mc_channel_type": "HASHTAG",
            "region_scope": None,
        },
    ]
    intent = [
        {
            "mc_channel_idx": 0,
            "name": "galloway",
            "mc_channel_type": "HASHTAG",
            "region_scope": None,
        },
    ]
    merged = merge_channel_region_scopes(device, intent)
    assert merged[0]["region_scope"] is None


def test_log_device_channels_always_logs_scope(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    log_device_channels(
        [
            {"mc_channel_idx": 0, "name": "Public", "mc_channel_type": "PUBLIC"},
            {
                "mc_channel_idx": 1,
                "name": "galloway",
                "mc_channel_type": "HASHTAG",
                "region_scope": "uk-wide",
            },
        ]
    )
    text = caplog.text
    assert "region_scope=(none)" in text
    assert "region_scope=uk-wide" in text


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


def test_read_device_channels_merges_scope_hints() -> None:
    mc = MagicMock()
    mc.commands.get_channel = AsyncMock(
        side_effect=[
            Event(
                EventType.CHANNEL_INFO,
                {"channel_name": "#galloway", "channel_idx": 0},
                {},
            ),
            Event(EventType.ERROR, {}, {}),
        ]
    )
    channels = asyncio.run(
        read_device_channels(
            mc,
            max_channels=2,
            scope_hints=[
                {
                    "mc_channel_idx": 0,
                    "name": "galloway",
                    "mc_channel_type": "HASHTAG",
                    "region_scope": "sample-west",
                },
            ],
        )
    )
    assert len(channels) == 1
    assert channels[0]["region_scope"] == "sample-west"


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


def test_apply_device_channels_sets_flood_scope() -> None:
    mc = MagicMock()
    mc.commands.set_channel = AsyncMock(
        return_value=Event(EventType.CHANNEL_INFO, {}, {})
    )
    mc.commands.set_flood_scope = AsyncMock(return_value=Event(EventType.OK, {}, {}))
    asyncio.run(
        apply_device_channels(
            mc,
            [
                {
                    "mc_channel_idx": 1,
                    "name": "galloway",
                    "mc_channel_type": "HASHTAG",
                    "region_scope": "sample-west",
                },
            ],
        )
    )
    mc.commands.set_flood_scope.assert_awaited_once_with("sample-west")
