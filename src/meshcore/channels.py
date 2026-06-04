"""Read and write MeshCore companion channel table via meshcore_py."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from meshcore import MeshCore
from meshcore.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHANNEL_SCAN = 16
APPLY_READBACK_DELAY_S = 2.0
# Companion protocol: delete channel = SET_CHANNEL with empty name + all-zero secret.
CLEAR_CHANNEL_SECRET = bytes(16)


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


async def _clear_device_channel_slot(meshcore: MeshCore, idx: int) -> bool:
    """
    Remove a channel slot (companion SET_CHANNEL with empty name).

    meshcore_py 2.3.x has no del_channel; pass explicit zero secret so the
    library does not derive one from the empty name hash.
    """
    evt = await meshcore.commands.set_channel(idx, "", CLEAR_CHANNEL_SECRET)
    if evt.type == EventType.ERROR:
        logger.warning("clear_channel(%s) failed: %s", idx, evt.payload)
        return False
    logger.info("MeshCore channel [%s] cleared (not in apply payload)", idx)
    return True


async def clear_unlisted_device_channels(
    meshcore: MeshCore,
    desired_channels: list[dict],
    *,
    max_channels: int = DEFAULT_MAX_CHANNEL_SCAN,
) -> None:
    """Clear device slots that have a name but are absent from the apply payload."""
    desired_indices = {
        int(ch["mc_channel_idx"])
        for ch in desired_channels
        if ch.get("mc_channel_idx") is not None
    }
    existing = await read_device_channels(
        meshcore, max_channels=max_channels, scope_hints=None
    )
    for row in existing:
        idx = int(row["mc_channel_idx"])
        if idx not in desired_indices:
            await _clear_device_channel_slot(meshcore, idx)


async def apply_device_channels(meshcore: MeshCore, channels: list[dict]) -> None:
    """
    Write channel list to device (UI push path).

    Clears any currently configured slot not listed in ``channels``, then writes
    each payload row so the radio matches the Meshflow feeder mirror layout.
    """
    await clear_unlisted_device_channels(meshcore, channels)
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


def _format_region_scope(scope: str | None) -> str:
    return scope if scope else "(none)"


def _channels_by_idx(channels: list[dict]) -> dict[int, dict]:
    by_idx: dict[int, dict] = {}
    for row in channels:
        if row.get("mc_channel_idx") is None:
            continue
        by_idx[int(row["mc_channel_idx"])] = row
    return by_idx


def _normalize_compare_name(entry: dict) -> str:
    name = str(entry.get("name") or "").strip()
    if str(entry.get("mc_channel_type", "PUBLIC")).upper() == "HASHTAG":
        name = name.lstrip("#")
    return name


def log_labeled_channel_config(label: str, channels: list[dict]) -> None:
    """Log apply DESIRED or READBACK channel rows (operator-visible in feeder logs)."""
    tag = label.upper()
    if not channels:
        logger.info("MeshCore apply %s: (no channels)", tag)
        return
    logger.info("MeshCore apply %s (%s channel(s)):", tag, len(channels))
    for ch in sorted(channels, key=lambda c: int(c["mc_channel_idx"])):
        idx = ch["mc_channel_idx"]
        typ = ch.get("mc_channel_type", "?")
        name = ch.get("name", "")
        logger.info(
            "  [%s] %s name=%r region_scope=%s",
            idx,
            typ,
            name,
            _format_region_scope(ch.get("region_scope")),
        )


def warn_apply_readback_mismatches(desired: list[dict], readback: list[dict]) -> None:
    """
    Compare apply payload to device readback (no scope_hints).

    region_scope mismatches are warned only when readback includes scope from
    CHANNEL_INFO; firmware often omits scope until per-slot scope is exposed.
    """
    read_by_idx = _channels_by_idx(readback)
    for want in sorted(desired, key=lambda c: int(c["mc_channel_idx"])):
        idx = int(want["mc_channel_idx"])
        got = read_by_idx.get(idx)
        if got is None:
            logger.warning(
                "MeshCore apply READBACK mismatch slot [%s]: desired present, no readback row",
                idx,
            )
            continue
        if _normalize_compare_name(want) != _normalize_compare_name(got):
            logger.warning(
                "MeshCore apply READBACK mismatch slot [%s]: desired name=%r readback name=%r",
                idx,
                want.get("name"),
                got.get("name"),
            )
        want_type = str(want.get("mc_channel_type", "PUBLIC")).upper()
        got_type = str(got.get("mc_channel_type", "PUBLIC")).upper()
        if want_type != got_type:
            logger.warning(
                "MeshCore apply READBACK mismatch slot [%s]: desired type=%s readback type=%s",
                idx,
                want_type,
                got_type,
            )
        want_scope = _normalize_region_scope(want.get("region_scope"))
        got_scope = got.get("region_scope")
        if got_scope is not None and want_scope != got_scope:
            logger.warning(
                "MeshCore apply READBACK mismatch slot [%s]: desired region_scope=%s readback region_scope=%s",
                idx,
                _format_region_scope(want_scope),
                _format_region_scope(got_scope),
            )


async def verify_apply_channels(meshcore: MeshCore, desired: list[dict]) -> None:
    """Log desired apply payload, read device without scope_hints, warn on mismatch."""
    log_labeled_channel_config("DESIRED", desired)
    await asyncio.sleep(APPLY_READBACK_DELAY_S)
    readback = await read_device_channels(meshcore, scope_hints=None)
    log_labeled_channel_config("READBACK", readback)
    warn_apply_readback_mismatches(desired, readback)


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
        logger.info(
            "  [%s] %s name=%r region_scope=%s",
            idx,
            typ,
            name,
            _format_region_scope(ch.get("region_scope")),
        )


def snapshot_sync_body(channels: list[dict]) -> dict:
    return {
        "channels": channels,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
