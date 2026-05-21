"""Read and write MeshCore companion channel table via meshcore_py."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from meshcore import MeshCore
from meshcore.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHANNEL_SCAN = 16


def _channel_entry_from_info(idx: int, payload: dict) -> Optional[dict]:
    name = str(payload.get("channel_name", "") or "").strip()
    if not name:
        return None
    if name.startswith("#"):
        return {
            "mc_channel_idx": idx,
            "name": name.lstrip("#")[:100] or f"channel {idx}",
            "mc_channel_type": "HASHTAG",
            "mc_hashtag": name.lstrip("#")[:64],
        }
    return {
        "mc_channel_idx": idx,
        "name": name[:100],
        "mc_channel_type": "PUBLIC",
        "mc_hashtag": None,
    }


def _describe_channel_event(idx: int, evt: Any) -> str:
    if evt.type == EventType.ERROR:
        payload = evt.payload if isinstance(evt.payload, dict) else {}
        return f"[{idx}] ERROR {payload.get('reason', payload)}"
    if evt.type == EventType.CHANNEL_INFO:
        payload = evt.payload if isinstance(evt.payload, dict) else {}
        name = payload.get("channel_name", "")
        return f"[{idx}] CHANNEL_INFO name={name!r}"
    return f"[{idx}] {evt.type}"


async def read_device_channels(
    meshcore: MeshCore,
    *,
    max_channels: int = DEFAULT_MAX_CHANNEL_SCAN,
) -> list[dict]:
    """Return channel snapshot rows for API mc-channel-sync."""
    channels: list[dict] = []
    scan_lines: list[str] = []
    for idx in range(max_channels):
        evt = await meshcore.commands.get_channel(idx)
        scan_lines.append(_describe_channel_event(idx, evt))
        if evt.type == EventType.ERROR:
            continue
        if evt.type != EventType.CHANNEL_INFO:
            continue
        payload = evt.payload if isinstance(evt.payload, dict) else {}
        entry = _channel_entry_from_info(idx, payload)
        if entry:
            channels.append(entry)
        elif str(payload.get("channel_name", "") or "").strip():
            logger.info(
                "MeshCore channel [%s] has name %r but was not mapped",
                idx,
                payload.get("channel_name"),
            )
    if not channels:
        logger.warning(
            "MeshCore get_channel scan found 0 named channels: %s",
            "; ".join(scan_lines) or "(no responses)",
        )
    return channels


async def apply_device_channels(meshcore: MeshCore, channels: list[dict]) -> None:
    """Write channel list to device (UI push path)."""
    for ch in channels:
        idx = int(ch["mc_channel_idx"])
        name = str(ch.get("name") or f"channel {idx}")
        ch_type = str(ch.get("mc_channel_type", "PUBLIC")).upper()
        if ch_type == "HASHTAG":
            tag = str(ch.get("mc_hashtag") or name).lstrip("#")
            name = f"#{tag}"
        evt = await meshcore.commands.set_channel(idx, name)
        if evt.type == EventType.ERROR:
            logger.warning("set_channel(%s) failed: %s", idx, evt.payload)


def log_device_channels(channels: list[dict]) -> None:
    """Log the device channel table at INFO (visible in docker logs on connect)."""
    if not channels:
        logger.info("MeshCore device channels: (none configured on device)")
        return
    logger.info("MeshCore device channels (%s):", len(channels))
    for ch in sorted(channels, key=lambda c: int(c["mc_channel_idx"])):
        idx = ch["mc_channel_idx"]
        typ = ch.get("mc_channel_type", "?")
        name = ch.get("name", "")
        tag = ch.get("mc_hashtag")
        if tag:
            logger.info(
                "  [%s] %s name=%r hashtag=%r",
                idx,
                typ,
                name,
                tag,
            )
        else:
            logger.info("  [%s] %s name=%r", idx, typ, name)


def snapshot_sync_body(channels: list[dict]) -> dict:
    return {
        "channels": channels,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
