"""Write MeshCore :class:`meshcore.events.Event` captures to JSON files."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _json_safe(obj: Any) -> Any:
    """Recursively convert payloads to JSON-serialisable structures."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def dump_meshcore_event(
    *,
    event_type: str,
    payload: Any,
    attributes: dict[str, Any],
    base_dir: Path,
) -> Path | None:
    """Write one event under ``base_dir/meshcore_packets/<event_type>/``.

    Returns the path written, or ``None`` if writing failed.
    """
    out_dir = base_dir / "meshcore_packets" / event_type
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = out_dir / f"{ts}.json"
    record = {
        "protocol": "meshcore",
        "event_type": event_type,
        "payload": _json_safe(payload),
        "attributes": _json_safe(attributes),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        return path
    except OSError as exc:
        logger.error("MeshCore dump failed: %s", exc)
        return None
