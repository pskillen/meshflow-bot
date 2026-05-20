"""Upload device channel snapshot to meshflow-api."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from src.meshcore.channels import read_device_channels, snapshot_sync_body

if TYPE_CHECKING:
    from src.api.StorageAPI import StorageAPIWrapper
    from src.meshcore.radio import MeshCoreRadio

logger = logging.getLogger(__name__)


def sync_channels_to_api(radio: "MeshCoreRadio", storage: "StorageAPIWrapper") -> bool:
    """Read channels from device and POST mc-channel-sync. Returns True on HTTP success."""
    if not radio.is_connected:
        logger.warning("MeshCore channel sync skipped: radio not connected")
        return False

    async def _read():
        mc = radio._meshcore  # noqa: SLF001 — intentional coupling for sync
        if mc is None:
            return []
        return await read_device_channels(mc)

    try:
        channels = radio.run_coroutine(_read())
    except Exception as exc:
        logger.exception("MeshCore read_device_channels failed: %s", exc)
        return False

    body = snapshot_sync_body(channels)
    return storage.post_mc_channel_sync(body)


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
