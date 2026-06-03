"""Tests for API-driven periodic MeshCore flood adverts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.meshcore.radio import (
    DEFAULT_MC_FLOOD_ADVERT_INTERVAL_HOURS,
    MeshCoreRadio,
)


def test_parse_flood_advert_interval_hours_defaults() -> None:
    assert (
        MeshCoreRadio.parse_flood_advert_interval_hours(None)
        == DEFAULT_MC_FLOOD_ADVERT_INTERVAL_HOURS
    )
    assert (
        MeshCoreRadio.parse_flood_advert_interval_hours({})
        == DEFAULT_MC_FLOOD_ADVERT_INTERVAL_HOURS
    )


def test_parse_flood_advert_interval_hours_clamps() -> None:
    assert (
        MeshCoreRadio.parse_flood_advert_interval_hours(
            {"mc_flood_advert_interval_hours": 1}
        )
        == 2.0
    )
    assert (
        MeshCoreRadio.parse_flood_advert_interval_hours(
            {"mc_flood_advert_interval_hours": 48}
        )
        == 24.0
    )
    assert (
        MeshCoreRadio.parse_flood_advert_interval_hours(
            {"mc_flood_advert_interval_hours": 12}
        )
        == 12.0
    )


def test_schedule_flood_advert_from_config() -> None:
    storage = MagicMock()
    storage.fetch_bot_config.return_value = {"mc_flood_advert_interval_hours": 8}

    radio = MeshCoreRadio.__new__(MeshCoreRadio)
    radio._flood_advert_task = None  # noqa: SLF001
    radio.schedule_flood_advert_periodic = MagicMock()
    radio.schedule_flood_advert_from_config(storage)

    storage.fetch_bot_config.assert_called_once()
    radio.schedule_flood_advert_periodic.assert_called_once_with(8.0)


def test_cancel_flood_advert_periodic() -> None:
    async def _runner() -> None:
        radio = MeshCoreRadio.__new__(MeshCoreRadio)
        loop = asyncio.get_running_loop()
        radio._loop = loop  # noqa: SLF001
        radio._flood_advert_task = None  # noqa: SLF001
        import threading

        radio._shutdown = threading.Event()
        radio._meshcore = MagicMock()
        radio._meshcore.is_connected = True
        radio._error_counter = MagicMock()

        radio.schedule_flood_advert_periodic(2.0)
        task = radio._flood_advert_task
        assert task is not None
        radio.cancel_flood_advert_periodic()
        assert radio._flood_advert_task is None
        task.cancel()
        await asyncio.sleep(0)

    asyncio.run(_runner())
