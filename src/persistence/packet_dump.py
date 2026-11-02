"""Lossless on-disk dump of received Meshtastic packets (fixture source).

Each file is ``{packet, raw_b64, meta}``:

* ``packet`` - the library's decoded dict, with every ``bytes`` value as base64
  (never a Python repr) and the protobuf object under ``raw`` removed.
* ``raw_b64`` - base64 of ``MeshPacket.SerializeToString()``. Protobuf keeps
  unknown fields, so fields the pinned library doesn't know (e.g. 2.8 signing,
  MeshPacket 22/23 and Data 10) survive and can be parsed later by a newer lib.
* ``meta`` - ``feeder_num``, ``feeder_fw``, ``lib_version``, ``captured_at``.

Env: ``DUMP_PACKETS_PORTNUMS`` (comma list or ``*``), ``DUMP_NODEDB`` (bool),
``DATA_DIR`` (data root; files go under ``<data dir>/packets/``). Private key
material is never written: NodeDB holds public keys only and config/security
is not dumped.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

NODEDB_DIRNAME = "_nodedb"

dump_portnums = os.getenv("DUMP_PACKETS_PORTNUMS", None)
if dump_portnums:
    dump_portnums = dump_portnums.split(",")
    dump_portnums = [p.strip().upper() for p in dump_portnums]
    # if any portnums == *, dump all portnums
    if "*" in dump_portnums:
        dump_portnums = ["*"]

    logger.info("Will dump all packets for portnums to JSON: %s", dump_portnums)
else:
    logger.info(
        "Not dumping packets - set DUMP_PACKETS_PORTNUMS to comma separated list of portnums to dump"
    )

dump_nodedb = os.getenv("DUMP_NODEDB", "false").strip().lower() in ("1", "true", "yes")


def resolve_data_dir() -> Path:
    """Data root, resolved like ``src.main`` (repo root / ``DATA_DIR``, default ``data``)."""
    return Path(__file__).parent.parent.parent / os.getenv("DATA_DIR", "data")


def lib_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("meshtastic")
    except Exception:
        return None


def json_safe(obj: Any) -> Any:
    """Recursively make *obj* JSON-serialisable; ``bytes`` become base64 strings."""
    if isinstance(obj, (bytes, bytearray)):
        return base64.b64encode(bytes(obj)).decode("ascii")
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _raw_b64(packet: dict) -> Optional[str]:
    raw = packet.get("raw")
    serialize = getattr(raw, "SerializeToString", None)
    if serialize is None:
        return None
    try:
        return base64.b64encode(serialize()).decode("ascii")
    except Exception as e:
        logger.error("Error serialising raw MeshPacket for dump: %s", e)
        return None


def dump_packet(
    packet: dict,
    *,
    feeder_num: Optional[int] = None,
    feeder_fw: Optional[str] = None,
    data_dir: Optional[Path] = None,
) -> None:
    global dump_portnums
    if not dump_portnums or len(dump_portnums) == 0:
        return

    portnum = packet["decoded"]["portnum"] if "decoded" in packet else "unknown"
    portnum = str(portnum).upper()

    if dump_portnums[0] != "*" and portnum not in dump_portnums:
        return

    base = Path(data_dir) if data_dir is not None else resolve_data_dir()
    portnum_dir = base / "packets" / portnum

    record = {
        "packet": json_safe({k: v for k, v in packet.items() if k != "raw"}),
        "raw_b64": _raw_b64(packet),
        "meta": {
            "feeder_num": feeder_num,
            "feeder_fw": feeder_fw,
            "lib_version": lib_version(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    try:
        portnum_dir.mkdir(parents=True, exist_ok=True)
        with open(portnum_dir / f"{_timestamp()}.json", "w") as f:
            json.dump(record, f, indent=4)
    except Exception as e:
        logger.error("Error dumping packet to JSON: %s", e)


def dump_nodes(
    nodes: Optional[dict], *, data_dir: Optional[Path] = None
) -> Optional[Path]:
    """Write ``interface.nodes`` to ``<data dir>/packets/_nodedb/<ts>.json`` if ``DUMP_NODEDB`` is on."""
    if not dump_nodedb or not nodes:
        return None
    base = Path(data_dir) if data_dir is not None else resolve_data_dir()
    out_dir = base / "packets" / NODEDB_DIRNAME
    path = out_dir / f"{_timestamp()}.json"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(json_safe(nodes), f, indent=4)
        return path
    except Exception as e:
        logger.error("Error dumping NodeDB to JSON: %s", e)
        return None
