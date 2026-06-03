"""Upload device channel snapshot to meshflow-api."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

CHANNEL_READ_DELAY_S = 2.0

from src.meshcore.channels import (
    log_device_channels,
    read_device_channels,
    snapshot_sync_body,
)

if TYPE_CHECKING:
    from src.api.StorageAPI import StorageAPIWrapper
    from src.meshcore.radio import MeshCoreRadio

logger = logging.getLogger(__name__)


async def read_channel_snapshot_async(
    radio: "MeshCoreRadio",
    *,
    scope_hints: list[dict] | None = None,
) -> Optional[dict]:
    """Read the device channel table once; return mc-channel-sync body or None."""
    if not radio.is_connected:
        logger.warning("MeshCore channel read skipped: radio not connected")
        return None

    mc = radio._meshcore  # noqa: SLF001 — intentional coupling for sync
    if mc is None:
        channels: list[dict] = []
    else:
        try:
            await asyncio.sleep(CHANNEL_READ_DELAY_S)
            channels = await read_device_channels(mc, scope_hints=scope_hints)
        except Exception as exc:
            logger.exception("MeshCore read_device_channels failed: %s", exc)
            return None

    log_device_channels(channels)
    return snapshot_sync_body(channels)


def post_channel_snapshot(storage: "StorageAPIWrapper", body: dict) -> bool:
    """POST a pre-built snapshot to one API destination."""
    ok = storage.post_mc_channel_sync(body)
    label = getattr(storage, "base_url", "storage")
    if ok:
        logger.info(
            "MeshCore channel sync posted to %s (%s channel(s))",
            label,
            len(body.get("channels") or []),
        )
    else:
        logger.warning(
            "MeshCore channel sync to %s failed (%s channel(s) in snapshot)",
            label,
            len(body.get("channels") or []),
        )
    return ok


async def sync_channels_to_storage_apis_async(
    radio: "MeshCoreRadio",
    storage_apis: list["StorageAPIWrapper"],
    *,
    scope_hints: list[dict] | None = None,
) -> None:
    """Read device channels once and POST the same snapshot to every configured API."""
    if not storage_apis:
        return
    body = await read_channel_snapshot_async(radio, scope_hints=scope_hints)
    if body is None:
        return
    for storage in storage_apis:
        post_channel_snapshot(storage, body)


async def sync_channels_to_api_async(
    radio: "MeshCoreRadio",
    storage: "StorageAPIWrapper",
    *,
    scope_hints: list[dict] | None = None,
) -> bool:
    """Read channels on the MeshCore asyncio loop and POST mc-channel-sync to one API."""
    body = await read_channel_snapshot_async(radio, scope_hints=scope_hints)
    if body is None:
        return False
    return post_channel_snapshot(storage, body)


def sync_channels_to_api(
    radio: "MeshCoreRadio",
    storage: "StorageAPIWrapper",
    *,
    scope_hints: list[dict] | None = None,
) -> bool:
    """Sync from a non-radio thread (e.g. WebSocket worker). Do not call from the radio loop."""
    if not hasattr(radio, "run_coroutine"):
        logger.warning("MeshCore channel sync skipped: radio has no run_coroutine")
        return False
    try:
        return radio.run_coroutine(
            sync_channels_to_api_async(radio, storage, scope_hints=scope_hints),
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


def sync_channels_after_apply(
    radio: "MeshCoreRadio",
    storage_apis: list["StorageAPIWrapper"],
    applied_channels: list[dict],
) -> None:
    """Re-read device channels and merge applied region_scope before posting to APIs."""
    if not hasattr(radio, "run_coroutine"):
        logger.warning("MeshCore post-apply sync skipped: radio has no run_coroutine")
        return
    try:
        radio.run_coroutine(
            sync_channels_to_storage_apis_async(
                radio,
                storage_apis,
                scope_hints=applied_channels,
            ),
            timeout=120.0,
        )
    except Exception as exc:
        logger.exception("MeshCore post-apply channel sync failed: %s", exc)
