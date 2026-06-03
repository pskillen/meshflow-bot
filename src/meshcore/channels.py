"""Read and write MeshCore companion channel table via meshcore_py."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from meshcore import MeshCore
from meshcore.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHANNEL_SCAN = 16


def _normalize_region_scope(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower().lstrip("#")
    if not raw or raw in ("*", "none", "null"):
        return None
    return raw[:29]


def merge_channel_region_scopes(
    device_channels: list[dict],
    intent_channels: list[dict] | None,
) -> list[dict]:
    """
    Overlay region_scope from an apply/sync intent onto device snapshot rows.

    Companion CHANNEL_INFO does not return per-channel scope yet; after apply we
    must carry scope from the operator payload so the API does not create duplicate
    unscoped canonical rows.
    """
    if not intent_channels:
        return device_channels

    intent_by_idx: dict[int, dict] = {}
    for row in intent_channels:
        if row.get("mc_channel_idx") is None:
            continue
        intent_by_idx[int(row["mc_channel_idx"])] = row

    merged: list[dict] = []
    for entry in device_channels:
        row = dict(entry)
        idx = int(row["mc_channel_idx"])
        intent = intent_by_idx.get(idx)
        if intent is not None and "region_scope" in intent:
            row["region_scope"] = _normalize_region_scope(intent.get("region_scope"))
        merged.append(row)
    return merged


def _channel_entry_from_info(idx: int, payload: dict) -> Optional[dict]:
    name = str(payload.get("channel_name", "") or "").strip()
    if not name:
        return None
    scope = (
        payload.get("region_scope")
        or payload.get("flood_scope")
        or payload.get("scope_name")
    )
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
        scope = payload.get("region_scope") or payload.get("scope_name")
        if scope:
            return f"[{idx}] CHANNEL_INFO name={name!r} region_scope={scope!r}"
        return f"[{idx}] CHANNEL_INFO name={name!r}"
    return f"[{idx}] {evt.type}"


async def _apply_active_flood_scope(
    meshcore: MeshCore, region_scope: str | None
) -> None:
    """
    Set the companion active flood scope (CMD_SET_FLOOD_SCOPE / set_flood_scope).

    This is the operator-facing scope used when sending on the active channel slot;
    firmware does not yet return per-channel scope in CHANNEL_INFO.
    """
    set_scope = getattr(getattr(meshcore, "commands", None), "set_flood_scope", None)
    if set_scope is None:
        logger.warning(
            "meshcore.commands.set_flood_scope unavailable; region_scope=%r not applied to radio",
            region_scope,
        )
        return
    scope_arg = region_scope if region_scope else "*"
    evt = await set_scope(scope_arg)
    if evt.type == EventType.ERROR:
        logger.warning("set_flood_scope(%r) failed: %s", scope_arg, evt.payload)


async def read_device_channels(
    meshcore: MeshCore,
    *,
    max_channels: int = DEFAULT_MAX_CHANNEL_SCAN,
    scope_hints: list[dict] | None = None,
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
    return merge_channel_region_scopes(channels, scope_hints)


async def apply_device_channels(meshcore: MeshCore, channels: list[dict]) -> None:
    """Write channel list to device (UI push path)."""
    for ch in channels:
        idx = int(ch["mc_channel_idx"])
        name = str(ch.get("name") or f"channel {idx}")
        ch_type = str(ch.get("mc_channel_type", "PUBLIC")).upper()
        region_scope = _normalize_region_scope(ch.get("region_scope"))
        if ch_type == "HASHTAG":
            tag = str(ch.get("name") or name).lstrip("#")
            name = f"#{tag}"
        evt = await meshcore.commands.set_channel(idx, name)
        if evt.type == EventType.ERROR:
            logger.warning("set_channel(%s) failed: %s", idx, evt.payload)
            continue
        await _apply_active_flood_scope(meshcore, region_scope)
        if region_scope:
            logger.info(
                "MeshCore channel [%s] set name=%r active flood scope=%r",
                idx,
                ch.get("name"),
                region_scope,
            )


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
        scope_label = scope if scope else "(none)"
        logger.info(
            "  [%s] %s name=%r region_scope=%s",
            idx,
            typ,
            name,
            scope_label,
        )


def snapshot_sync_body(channels: list[dict]) -> dict:
    return {
        "channels": channels,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
