"""Upload device channel snapshot to meshflow-api."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from src.meshcore.channels import (
    log_device_channels,
    read_device_channels,
    snapshot_sync_body,
)

if TYPE_CHECKING:
    from src.api.StorageAPI import StorageAPIWrapper
    from src.meshcore.radio import MeshCoreRadio

logger = logging.getLogger(__name__)


async def sync_channels_to_api_async(
    radio: "MeshCoreRadio", storage: "StorageAPIWrapper"
) -> bool:
    """Read channels on the MeshCore asyncio loop and POST mc-channel-sync."""
    if not radio.is_connected:
        logger.warning("MeshCore channel sync skipped: radio not connected")
        return False

    mc = radio._meshcore  # noqa: SLF001 — intentional coupling for sync
    if mc is None:
        channels: list[dict] = []
    else:
        try:
            channels = await read_device_channels(mc)
        except Exception as exc:
            logger.exception("MeshCore read_device_channels failed: %s", exc)
            return False

    log_device_channels(channels)
    body = snapshot_sync_body(channels)
    ok = storage.post_mc_channel_sync(body)
    if ok:
        logger.info(
            "MeshCore channel sync posted to API (%s channel(s))",
            len(channels),
        )
    else:
        logger.warning(
            "MeshCore channel sync to API failed (%s channel(s) read from device)",
            len(channels),
        )
    return ok


def sync_channels_to_api(radio: "MeshCoreRadio", storage: "StorageAPIWrapper") -> bool:
    """Sync from a non-radio thread (e.g. WebSocket worker). Do not call from the radio loop."""
    if not hasattr(radio, "run_coroutine"):
        logger.warning("MeshCore channel sync skipped: radio has no run_coroutine")
        return False
    try:
        return radio.run_coroutine(
            sync_channels_to_api_async(radio, storage),
            timeout=120.0,
        )
    except Exception as exc:
        logger.exception("MeshCore channel sync failed: %s", exc)
        return False


def apply_channels_on_device(radio: "MeshCoreRadio", channels: list[dict]) -> bool:
    """Apply WS command payload to device, then caller should re-sync API."""
    from src.meshcore.channels import apply_device_channels

    async def _apply():
        mc = radio._meshcore  # noqa: SLF001
        if mc is None:
            raise RuntimeError("MeshCore not connected")
        await apply_device_channels(mc, channels)

    try:
        radio.run_coroutine(_apply())
        return True
    except Exception as exc:
        logger.exception("MeshCore apply_device_channels failed: %s", exc)
        return False
