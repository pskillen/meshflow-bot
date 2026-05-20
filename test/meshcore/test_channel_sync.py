"""Tests for :mod:`src.meshcore.channel_sync`."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.meshcore.channel_sync import apply_channels_on_device, sync_channels_to_api


class _MeshCoreRadioStub:
    def __init__(
        self,
        *,
        connected: bool = True,
        meshcore=None,
        run_raises: Exception | None = None,
    ):
        self.is_connected = connected
        self._meshcore = meshcore
        self._run_raises = run_raises

    def run_coroutine(self, coro, *, timeout: float = 30.0):
        if self._run_raises is not None:
            raise self._run_raises
        if asyncio.iscoroutine(coro):
            return asyncio.run(coro)
        return None


def test_sync_channels_skipped_when_disconnected() -> None:
    radio = _MeshCoreRadioStub(connected=False)
    storage = MagicMock()
    assert sync_channels_to_api(radio, storage) is False
    storage.post_mc_channel_sync.assert_not_called()


def test_sync_channels_posts_snapshot() -> None:
    radio = _MeshCoreRadioStub(connected=True, meshcore=MagicMock())
    storage = MagicMock()
    storage.post_mc_channel_sync.return_value = True
    channels = [{"mc_channel_idx": 0, "name": "Public", "mc_channel_type": "PUBLIC"}]
    with patch(
        "src.meshcore.channel_sync.read_device_channels",
        new_callable=AsyncMock,
        return_value=channels,
    ):
        assert sync_channels_to_api(radio, storage) is True
    storage.post_mc_channel_sync.assert_called_once()
    body = storage.post_mc_channel_sync.call_args[0][0]
    assert body["channels"][0]["name"] == "Public"
    assert "synced_at" in body


def test_sync_channels_returns_false_when_read_fails() -> None:
    radio = _MeshCoreRadioStub(connected=True, run_raises=RuntimeError("loop down"))
    storage = MagicMock()
    assert sync_channels_to_api(radio, storage) is False
    storage.post_mc_channel_sync.assert_not_called()


def test_sync_channels_empty_when_meshcore_none() -> None:
    radio = _MeshCoreRadioStub(connected=True, meshcore=None)
    storage = MagicMock()
    storage.post_mc_channel_sync.return_value = True
    assert sync_channels_to_api(radio, storage) is True
    assert storage.post_mc_channel_sync.call_args[0][0]["channels"] == []


def test_apply_channels_success() -> None:
    radio = _MeshCoreRadioStub(connected=True, meshcore=MagicMock())
    channels = [
        {
            "mc_channel_idx": 1,
            "name": "galloway",
            "mc_channel_type": "HASHTAG",
            "mc_hashtag": "galloway",
        }
    ]
    with patch(
        "src.meshcore.channels.apply_device_channels", new_callable=AsyncMock
    ) as apply_mock:
        assert apply_channels_on_device(radio, channels) is True
        apply_mock.assert_awaited_once()


def test_apply_channels_fails_when_not_connected() -> None:
    radio = _MeshCoreRadioStub(connected=True, meshcore=None)
    assert (
        apply_channels_on_device(radio, [{"mc_channel_idx": 0, "name": "x"}]) is False
    )


def test_apply_channels_returns_false_on_exception() -> None:
    radio = _MeshCoreRadioStub(connected=True, run_raises=OSError("serial gone"))
    assert (
        apply_channels_on_device(radio, [{"mc_channel_idx": 0, "name": "x"}]) is False
    )
