"""Tests for one-shot flood advert on MeshCore connect."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from meshcore.events import Event, EventType

from src.meshcore.radio import MeshCoreRadio


def test_schedule_initial_flood_advert_sends_on_loop() -> None:
    async def _runner() -> None:
        radio = MeshCoreRadio.__new__(MeshCoreRadio)
        loop = asyncio.get_running_loop()
        radio._loop = loop  # noqa: SLF001
        radio._error_counter = MagicMock()

        mc = MagicMock()
        mc.is_connected = True
        mc.commands.send_advert = AsyncMock(
            return_value=Event(EventType.OK, {}, {})
        )
        radio._meshcore = mc

        radio.schedule_initial_flood_advert()
        await asyncio.sleep(0.05)

        mc.commands.send_advert.assert_awaited_once_with(flood=True)

    asyncio.run(_runner())


def test_schedule_initial_flood_advert_logs_error_event() -> None:
    async def _runner() -> None:
        radio = MeshCoreRadio.__new__(MeshCoreRadio)
        loop = asyncio.get_running_loop()
        radio._loop = loop  # noqa: SLF001
        radio._error_counter = MagicMock()

        mc = MagicMock()
        mc.is_connected = True
        mc.commands.send_advert = AsyncMock(
            return_value=Event(EventType.ERROR, "device busy", {})
        )
        radio._meshcore = mc

        radio.schedule_initial_flood_advert()
        await asyncio.sleep(0.05)

        mc.commands.send_advert.assert_awaited_once_with(flood=True)

    asyncio.run(_runner())
