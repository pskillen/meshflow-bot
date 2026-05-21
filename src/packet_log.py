"""Optional console logging of abridged packet summaries (``LOG_PACKETS=true``)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from src.radio.events import IncomingPacket

logger = logging.getLogger(__name__)


def log_packets_enabled() -> bool:
    return os.getenv("LOG_PACKETS", "false").lower() in ("1", "true", "yes")


def _truncate(value: Any, *, max_len: int = 80) -> str:
    text = str(value).replace("\n", " ")
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def log_incoming_packet(event: IncomingPacket) -> None:
    """Log a one-line summary of an MC or MT packet when ``LOG_PACKETS`` is enabled."""
    if not log_packets_enabled():
        return

    raw = event.raw if isinstance(event.raw, dict) else {}
    if raw.get("meshcore") or raw.get("protocol") == "meshcore":
        evt = raw.get("type") or raw.get("event_type") or event.portnum
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        detail = _mc_payload_detail(payload)
        logger.info(
            "MC %s from=%s ch=%s%s",
            evt,
            event.from_id or "-",
            event.channel,
            detail,
        )
        return

    if isinstance(raw, dict) and "decoded" in raw:
        decoded = raw.get("decoded") if isinstance(raw.get("decoded"), dict) else {}
        portnum = decoded.get("portnum") or event.portnum
        logger.info(
            "MT %s from=%s to=%s ch=%s id=%s%s",
            portnum,
            event.from_id or "-",
            event.to_id or "-",
            event.channel,
            raw.get("id", "-"),
            _mt_decoded_detail(decoded),
        )
        return

    logger.info(
        "pkt %s from=%s to=%s ch=%s decoded=%s",
        event.portnum,
        event.from_id or "-",
        event.to_id or "-",
        event.channel,
        event.has_decoded,
    )


def _mc_payload_detail(payload: dict) -> str:
    if not payload:
        return ""
    if "text" in payload:
        return f' text="{_truncate(payload.get("text"), max_len=60)}"'
    if payload.get("payload_typename"):
        return f" typename={payload['payload_typename']}"
    if payload.get("public_key"):
        pk = str(payload["public_key"])
        return f" pubkey={pk[:12]}…"
    if payload.get("pubkey_prefix"):
        return f" prefix={payload['pubkey_prefix']}"
    if payload.get("channel_name"):
        return f' name="{_truncate(payload["channel_name"], max_len=40)}"'
    return ""


def _mt_decoded_detail(decoded: dict) -> str:
    if not decoded:
        return ""
    if decoded.get("portnum") == "TEXT_MESSAGE_APP":
        text = decoded.get("text") or (decoded.get("payload") or {}).get("text")
        if text:
            return f' text="{_truncate(text, max_len=60)}"'
    if decoded.get("portnum") == "POSITION_APP":
        pos = decoded.get("position") or (decoded.get("payload") or {}).get("position")
        if isinstance(pos, dict) and "latitudeI" in pos:
            return " pos=…"
    return ""
