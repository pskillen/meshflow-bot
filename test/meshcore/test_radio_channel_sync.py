"""Regression: channel sync must not block the MeshCore asyncio loop."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.meshcore.radio import MeshCoreRadio
from src.radio.errors import RadioError


def test_run_coroutine_rejects_call_from_radio_loop() -> None:
    async def _runner():
        radio = MeshCoreRadio.__new__(MeshCoreRadio)
        loop = asyncio.get_running_loop()
        radio._loop = loop  # noqa: SLF001

        async def _noop():
            return None

        with pytest.raises(RadioError, match="radio event loop"):
            radio.run_coroutine(_noop())

    asyncio.run(_runner())


def test_schedule_channel_sync_runs_on_loop() -> None:
    async def _runner():
        radio = MeshCoreRadio.__new__(MeshCoreRadio)
        loop = asyncio.get_running_loop()
        radio._loop = loop  # noqa: SLF001
        radio._meshcore = MagicMock()
        radio._meshcore.is_connected = True

        storage = MagicMock()
        storage.base_url = "http://api.test"
        done = asyncio.Event()

        async def _fake_sync(_radio, _storages, **kwargs):
            done.set()

        with patch(
            "src.meshcore.channel_sync.sync_channels_to_storage_apis_async",
            side_effect=_fake_sync,
        ):
            radio.schedule_channel_sync([storage])
            await asyncio.wait_for(done.wait(), timeout=1.0)

    asyncio.run(_runner())


def test_schedule_channel_sync_from_worker_thread() -> None:
    """WS apply_mc_channel_config thread must schedule sync on the radio loop."""

    async def _runner():
        radio = MeshCoreRadio.__new__(MeshCoreRadio)
        loop = asyncio.get_running_loop()
        radio._loop = loop  # noqa: SLF001
        radio._meshcore = MagicMock()
        radio._meshcore.is_connected = True

        storage = MagicMock()
        storage.base_url = "http://api.test"
        done = asyncio.Event()

        async def _fake_sync(_radio, _storages, **kwargs):
            done.set()

        with patch(
            "src.meshcore.channel_sync.sync_channels_to_storage_apis_async",
            side_effect=_fake_sync,
        ):
            err: list[BaseException] = []

            def _worker():
                try:
                    radio.schedule_channel_sync([storage])
                except BaseException as exc:
                    err.append(exc)

            t = threading.Thread(target=_worker)
            t.start()
            t.join(timeout=2.0)
            assert not err, err
            await asyncio.wait_for(done.wait(), timeout=1.0)

    asyncio.run(_runner())
