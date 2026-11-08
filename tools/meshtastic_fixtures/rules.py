"""Shared, stdlib-only rules for the Meshtastic packet fixtures.

Used by ``build_fixtures.py`` (to label and count) and ``check_fixtures.py``
(to verify the committed tree). Nothing here imports ``meshtastic`` or
``google.protobuf``.

>>> classify_kind({"from": 5}, 5)
'self'
>>> classify_kind({"from": 6, "transportMechanism": "TRANSPORT_LORA", "priority": "BACKGROUND"}, 5)
'replay'
>>> classify_kind({"from": 6, "rxRssi": -80, "transportMechanism": "TRANSPORT_LORA", "priority": "BACKGROUND"}, 5)
'live'
"""

from __future__ import annotations

import base64
import re
import statistics
import zlib
from typing import Any, Iterable, Iterator, Optional

# One degree of latitude is 1e7 in the protobuf's fixed-point unit; 0.1 deg is 1e6.
GRID = 1_000_000

KINDS = ("self", "live", "replay")

SECRET_KEY_RE = re.compile(
    r"privateKey|private_key|psk|wifi_psk|wifiPsk|password|deviceId"
)

POSITION_PORT = "POSITION_APP"


def node_id_str(num: int) -> str:
    """``!`` + 8 hex nibbles.

    >>> node_id_str(3769067321)
    '!e0a76739'
    """
    return f"!{num & 0xFFFFFFFF:08x}"


def classify_kind(packet: dict, feeder_num: Optional[int]) -> str:
    """``self`` | ``replay`` | ``live`` by the brief's rule.

    ``replay``: not ours, no ``rxRssi`` key, ``transportMechanism`` is
    ``TRANSPORT_LORA`` and ``priority`` is ``BACKGROUND``. (MQTT-downlinked
    live packets also lack an RSSI, which is why the transport matters.)
    """
    if feeder_num is not None and packet.get("from") == feeder_num:
        return "self"
    if (
        "rxRssi" not in packet
        and packet.get("transportMechanism") == "TRANSPORT_LORA"
        and packet.get("priority") == "BACKGROUND"
    ):
        return "replay"
    return "live"


def port_of(packet: dict) -> str:
    """Port name, or ``ENCRYPTED`` when the packet has no ``decoded``."""
    decoded = packet.get("decoded")
    if isinstance(decoded, dict):
        return str(decoded.get("portnum", "UNKNOWN"))
    return "ENCRYPTED"


_NON_VARIANT = frozenset({"time", "raw"})


def telemetry_variant(packet: dict) -> Optional[str]:
    telemetry = (packet.get("decoded") or {}).get("telemetry") or {}
    for key, value in telemetry.items():
        if key not in _NON_VARIANT and isinstance(value, dict):
            return key
    return None


# --- walking -------------------------------------------------------------


def walk_dicts(obj: Any) -> Iterator[dict]:
    """Every dict nested anywhere in *obj* (including *obj*)."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_dicts(item)


def secret_keys(obj: Any) -> list[str]:
    """Names of keys that look like key material, config secrets or a device id."""
    return sorted(
        {k for d in walk_dicts(obj) for k in d if SECRET_KEY_RE.search(str(k))}
    )


# --- positions -----------------------------------------------------------

_COORD_I = ("latitudeI", "longitudeI")
_COORD_F = ("latitude", "longitude")


def round_i(value: int) -> int:
    """Round a fixed-point coordinate to the 0.1 deg grid; zero stays zero.

    >>> round_i(559874048), round_i(-36372480), round_i(0)
    (560000000, -36000000, 0)
    """
    return int(round(value, -6))


def on_grid(value: Any) -> bool:
    return isinstance(value, int) and value % GRID == 0


def position_dicts(obj: Any) -> Iterator[dict]:
    """Dicts that carry coordinates (``latitudeI``/``longitudeI`` or the floats)."""
    for d in walk_dicts(obj):
        if any(k in d for k in _COORD_I + _COORD_F):
            yield d


def grid_violations(obj: Any) -> list[str]:
    """Describe every coordinate in *obj* that is off the 0.1 deg grid."""
    bad: list[str] = []
    for d in position_dicts(obj):
        for key in _COORD_I:
            if key in d and not on_grid(d[key]):
                bad.append(f"{key}={d[key]}")
        for key in _COORD_F:
            if key in d:
                i = d.get(key + "I")
                if i is None:
                    i = round(d[key] * 1e7)
                    if not on_grid(i):
                        bad.append(f"{key}={d[key]}")
                elif d[key] != i / 1e7:
                    bad.append(f"{key}={d[key]} disagrees with {key}I={i}")
    return bad


def count_positions(obj: Any) -> int:
    """``position`` objects under *obj* that carry a fixed-point coordinate.

    >>> count_positions({"decoded": {"position": {"latitudeI": 1, "raw": {"latitudeI": 1}}}})
    1
    """
    return sum(
        1
        for d in walk_dicts(obj)
        if isinstance(d.get("position"), dict)
        and any(k in d["position"] for k in _COORD_I)
    )


# --- sender identity -----------------------------------------------------


def crc32_of_pubkey(pubkey_b64: str) -> int:
    return zlib.crc32(base64.b64decode(pubkey_b64)) & 0xFFFFFFFF


def mac_number(macaddr_b64: Optional[str]) -> Optional[int]:
    """Last four bytes of a 6-byte MAC (a <=2.7 node number); None if unusable."""
    if not macaddr_b64:
        return None
    try:
        mac = base64.b64decode(macaddr_b64)
    except ValueError:
        return None
    if len(mac) != 6 or not any(mac):
        return None
    return int.from_bytes(mac[2:], "big")


def collect_users(records: Iterable[dict], nodedb: dict) -> dict[int, dict]:
    """num -> user dict, from the NodeDB plus every NODEINFO in the capture."""
    users: dict[int, dict] = {}
    for entry in nodedb.values():
        user = entry.get("user")
        if isinstance(user, dict) and "num" in entry:
            users.setdefault(entry["num"], {}).update(user)
    for rec in records:
        packet = rec["packet"]
        user = (packet.get("decoded") or {}).get("user")
        if isinstance(user, dict) and "from" in packet:
            users.setdefault(packet["from"], {}).update(user)
    return users


def id_scheme(num: int, user: Optional[dict]) -> str:
    """``crc32`` | ``mac`` | ``neither`` | ``no_user`` for one sender."""
    if not user or not (user.get("publicKey") or user.get("macaddr")):
        return "no_user"
    if user.get("publicKey") and crc32_of_pubkey(user["publicKey"]) == num:
        return "crc32"
    if mac_number(user.get("macaddr")) == num:
        return "mac"
    return "neither"


def sender_schemes(
    records: list[dict], nodedb: dict, feeder_num: Optional[int]
) -> dict[int, str]:
    """Scheme of every distinct sender (the feeder included)."""
    users = collect_users(records, nodedb)
    nums = {r["packet"]["from"] for r in records if "from" in r["packet"]}
    if feeder_num is not None:
        nums.add(feeder_num)
    return {n: id_scheme(n, users.get(n)) for n in sorted(nums)}


def zeroed_mac_senders(
    records: list[dict], nodedb: dict, feeder_num: Optional[int]
) -> int:
    """Senders (not the feeder) whose only identity is a zeroed MAC and who match no scheme."""
    users = collect_users(records, nodedb)
    schemes = sender_schemes(records, nodedb, feeder_num)
    n = 0
    for num, scheme in schemes.items():
        if num == feeder_num or scheme != "neither":
            continue
        mac = (users.get(num) or {}).get("macaddr")
        if mac and not any(base64.b64decode(mac)):
            n += 1
    return n


# --- counts --------------------------------------------------------------


def median_interval(times: list[float]) -> float:
    """Median gap between consecutive samples, 0 with fewer than two.

    >>> median_interval([0.0, 60.0, 121.0])
    60.5
    >>> median_interval([1.0])
    0
    """
    if len(times) < 2:
        return 0
    gaps = [b - a for a, b in zip(times, times[1:])]
    return round(statistics.median(gaps), 1)


def recount(records: list[dict], nodedb: dict, feeder_num: int) -> dict:
    """The manifest's derived sections, recomputed from the records alone."""
    by_kind: dict[str, int] = {}
    by_port: dict[str, int] = {}
    by_port_and_kind: dict[str, dict[str, int]] = {}
    for rec in records:
        kind, port = rec["kind"], port_of(rec["packet"])
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_port[port] = by_port.get(port, 0) + 1
        slot = by_port_and_kind.setdefault(port, {})
        slot[kind] = slot.get(kind, 0) + 1

    schemes = sender_schemes(records, nodedb, feeder_num)
    counted = {n: s for n, s in schemes.items() if n != feeder_num}
    id_counts = {"mac": 0, "crc32": 0, "neither": 0, "no_user": 0}
    for scheme in counted.values():
        id_counts[scheme] += 1

    def self_times(variant: str) -> list[float]:
        return [
            r["t_host"]
            for r in records
            if r["kind"] == "self"
            and telemetry_variant(r["packet"]) == variant
            and (r["packet"].get("decoded") or {}).get("portnum") == "TELEMETRY_APP"
        ]

    start = records[0]["t_host"] if records else 0.0
    replays = [r for r in records if r["kind"] == "replay"]
    hop_starts = sorted(
        {r["packet"]["hopStart"] for r in replays if "hopStart" in r["packet"]}
    )
    device = self_times("deviceMetrics")
    return {
        "counts": {
            "total": len(records),
            "by_kind": dict(sorted(by_kind.items())),
            "by_port": dict(sorted(by_port.items())),
            "by_port_and_kind": {
                p: dict(sorted(k.items())) for p, k in sorted(by_port_and_kind.items())
            },
        },
        "senders": {
            "count": len(counted),
            "by_id_scheme": id_counts,
            "mac_zeroed": zeroed_mac_senders(records, nodedb, feeder_num),
        },
        "self_telemetry": {
            "deviceMetrics": {
                "count": len(device),
                "median_interval_s": median_interval(device),
            },
            "localStats": {"count": len(self_times("localStats"))},
        },
        "replay_burst": {
            "count": len(replays),
            "within_s_of_start": (
                round(max(r["t_host"] for r in replays) - start, 1) if replays else 0
            ),
            "hop_start_values": hop_starts,
        },
        "scrub_positions": {
            "positions_rounded": sum(count_positions(r["packet"]) for r in records),
            "nodedb_positions_rounded": count_positions(nodedb),
        },
    }


def replay_ids(records: list[dict]) -> set[int]:
    return {
        r["packet"]["id"] for r in records if r["kind"] == "replay" and "id" in r["packet"]
    }


# --- labels --------------------------------------------------------------


def labels_for(
    record: dict,
    *,
    feeder_fw: str,
    scheme: str,
    stable_replay: bool = False,
) -> list[str]:
    """Subset labels for one scrubbed record (see the README for the list)."""
    packet = record["packet"]
    kind = record["kind"]
    port = port_of(packet)
    labels = [
        "feeder:2.8" if feeder_fw.startswith("2.8") else "feeder:2.7",
        f"kind:{kind}",
        f"port:{port}",
    ]
    variant = telemetry_variant(packet) if port == "TELEMETRY_APP" else None
    if variant:
        labels.append(f"variant:{variant}")
    labels.append(
        "sender-id:" + (scheme if scheme in ("mac", "crc32") else "unknown")
    )
    if "rxTime" not in packet:
        labels.append("no-rx-time")
    if "fromId" in packet and packet["fromId"] is None:
        labels.append("from-id-null")
    if "hopStart" in packet and "hopLimit" not in packet:
        labels.append("hops-exhausted")
    if (
        kind == "replay"
        and "hopStart" in packet
        and packet.get("hopStart") == packet.get("hopLimit")
    ):
        labels.append("fake-direct")
    bitfield = (packet.get("decoded") or {}).get("bitfield")
    if bitfield is not None:
        labels.append(f"bitfield:{bitfield}")
    if packet.get("channel"):
        labels.append(f"channel:{packet['channel']}")
    if stable_replay:
        labels.append("stable-replay-id")
    return labels
