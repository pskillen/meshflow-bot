"""Read and write MeshCore companion channel table via meshcore_py."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from meshcore import MeshCore
from meshcore.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHANNEL_SCAN = 16
_scope_read_logged = False


def _normalize_region_scope(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower().lstrip("#")
    if not raw or raw in ("*", "none", "null"):
        return None
    return raw[:29]


def _channel_entry_from_info(idx: int, payload: dict) -> Optional[dict]:
    name = str(payload.get("channel_name", "") or "").strip()
    if not name:
        return None
    scope = payload.get("region_scope") or payload.get("flood_scope")
    region_scope = _normalize_region_scope(scope)
    if name.startswith("#"):
        tag = name.lstrip("#")[:100] or f"channel {idx}"
        return {
            "mc_channel_idx": idx,
            "name": tag,
            "mc_channel_type": "HASHTAG",
            "region_scope": region_scope,
        }
    return {
        "mc_channel_idx": idx,
        "name": name[:100],
        "mc_channel_type": "PUBLIC",
        "region_scope": region_scope,
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


async def _apply_region_scope(meshcore: MeshCore, region_scope: str | None) -> None:
    """Best-effort scope write when meshcore_py exposes set_flood_scope."""
    if not region_scope:
        return
    set_scope = getattr(getattr(meshcore, "commands", None), "set_flood_scope", None)
    if set_scope is None:
        logger.debug(
            "meshcore.commands.set_flood_scope not available; region_scope=%r not written to device",
            region_scope,
        )
        return
    evt = await set_scope(region_scope)
    if evt.type == EventType.ERROR:
        logger.warning("set_flood_scope(%r) failed: %s", region_scope, evt.payload)


async def read_device_channels(
    meshcore: MeshCore,
    *,
    max_channels: int = DEFAULT_MAX_CHANNEL_SCAN,
) -> list[dict]:
    """Return channel snapshot rows for API mc-channel-sync."""
    global _scope_read_logged
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
            if entry.get("region_scope") is None and not _scope_read_logged:
                logger.debug(
                    "Per-channel region_scope not returned by companion CHANNEL_INFO; syncing null"
                )
                _scope_read_logged = True
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
            tag = str(ch.get("name") or name).lstrip("#")
            name = f"#{tag}"
        evt = await meshcore.commands.set_channel(idx, name)
        if evt.type == EventType.ERROR:
            logger.warning("set_channel(%s) failed: %s", idx, evt.payload)
            continue
        await _apply_region_scope(meshcore, _normalize_region_scope(ch.get("region_scope")))


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
        scope = ch.get("region_scope")
        if scope:
            logger.info("  [%s] %s name=%r region_scope=%r", idx, typ, name, scope)
        else:
            logger.info("  [%s] %s name=%r", idx, typ, name)


def snapshot_sync_body(channels: list[dict]) -> dict:
    return {
        "channels": channels,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
