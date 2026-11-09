#!/usr/bin/env python3
"""Turn a raw capture into a scrubbed, labelled fixture directory.

Never commit raw capture output: it holds third parties' real positions. Run
this first; commit only what it writes.

    python tools/meshtastic_fixtures/build_fixtures.py <input> \\
        --capture-id <id> --out docs/meshtastic_packets/2.8/captures/<id>

``<input>`` is either

* an fx1 capture: ``<stem>.jsonl`` beside ``<stem>_meta.json`` and
  ``<stem>_nodedb.json`` (written by ``tools/meshtastic_capture/capture.py``), or
* a bot dump tree (``<DATA_DIR>`` holding ``packets/<PORTNUM>/*.json``,
  ``replay/<PORTNUM>/*.json`` and ``packets/_nodedb/*.json``, written by the bot
  with ``DUMP_PACKETS_PORTNUMS=*`` and ``DUMP_NODEDB=true``).

Output (deterministic): ``capture.jsonl``, ``nodedb.json``, ``manifest.json``.

    python tools/meshtastic_fixtures/build_fixtures.py --subset docs/meshtastic_packets/2.8

rebuilds ``subset.json`` (the contract with the api repo's tests) from the
committed captures.

Scrub rule: every latitude and longitude is rounded to 0.1 deg, in the packet
dict, the ``Position`` payload, the ``MeshPacket`` bytes and the NodeDB.
Private key material, ``deviceId`` and other people's text messages are never
written. Needs ``meshtastic`` (for its protobufs); the checker does not.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.meshtastic_fixtures import rules  # noqa: E402

SCRUB_RULE = "lat/lon rounded to 0.1 deg"
BASE_SCRUB = {"rule": SCRUB_RULE}

# --- the subset (the contract with the api repo's tests) ----------------
# key, kind, port, telemetry variant, sender, why
# The Xiao captures' rows are a contract with the api repo: their labels never change.
FROZEN_SHORTS = frozenset({"x27", "x28", "x28h4", "x28f"})
SUBSET: list[tuple[str, str, str, Optional[str], str, str]] = [
    ("x27-L1", "self", "TELEMETRY_APP", "deviceMetrics", "!1a83cf89", "2.7 self telemetry (cadence)"),
    ("x27-L27", "self", "TELEMETRY_APP", "localStats", "!1a83cf89", "2.7 self localStats"),
    ("x27-L5", "live", "NODEINFO_APP", None, "!433b10bc", "2.7 feeder, MAC-id sender"),
    ("x27-L7", "live", "POSITION_APP", None, "!60476689", "7/5 hops"),
    ("x27-L9", "live", "TELEMETRY_APP", "environmentMetrics", "!e27aee72", "fromId null"),
    ("x27-L10", "live", "TELEMETRY_APP", "deviceMetrics", "!229a5f0a", ""),
    ("x27-L12", "live", "POSITION_APP", None, "!698239c8", "hopLimit absent (0): hops exhausted"),
    ("x27-L23", "live", "NODEINFO_APP", None, "!a0cc75a0", "bitfield 2, 3/0"),
    ("x27-L37", "live", "ENCRYPTED", None, "!f90bb907", "channel 9, no decoded: bot never uploads"),
    ("x28-L1", "live", "NODEINFO_APP", None, "!7d085abc", "live 3/0 during the burst"),
    ("x28-L2", "replay", "POSITION_APP", None, "!0324c4a1", "replay, hopLimit 0"),
    ("x28-L4", "replay", "POSITION_APP", None, "!0ec53f95", "replay with hopStart == hopLimit: fake direct"),
    ("x28-L5", "replay", "POSITION_APP", None, "!29212d31", "replay 3/1"),
    ("x28-L41", "replay", "TELEMETRY_APP", "deviceMetrics", "!0324c4a1", "replay, hopLimit 0"),
    ("x28-L42", "replay", "TELEMETRY_APP", "deviceMetrics", "!0ec53f95", "fake direct"),
    ("x28-L43", "replay", "TELEMETRY_APP", "deviceMetrics", "!1f8d7181", "replay 3/1"),
    ("x28-L80", "self", "TELEMETRY_APP", "deviceMetrics", "!e0a76739", "2.8 self telemetry (every ~60 s)"),
    ("x28-L104", "self", "TELEMETRY_APP", "localStats", "!e0a76739", ""),
    ("x28-L81", "live", "POSITION_APP", None, "!7bc13c91", "bitfield 1"),
    ("x28-L83", "live", "STORE_FORWARD_APP", None, "!a35ae558", "GenericPacket on the api"),
    ("x28-L85", "live", "NODEINFO_APP", None, "!23c3c49f", "2.8 sender (number = crc32 of key): 2.8 x 2.8 cell"),
    ("x28-L86", "live", "POSITION_APP", None, "!f8185202", "6/5"),
    ("x28-L95", "live", "TELEMETRY_APP", "deviceMetrics", "!2a83b265", ""),
    ("x28h4-L1", "self", "ROUTING_APP", None, "!e0a76739", "self ACK, pkiEncrypted"),
    ("x28h4-L2", "live", "TELEMETRY_APP", "environmentMetrics", "!229a5f0a", ""),
    ("x28h4-L4", "replay", "POSITION_APP", None, "!0ec53f95", "same id as x28-L4, hops 4/4: stable replay id across reconnects"),
    ("x28f-L1", "self", "TELEMETRY_APP", "deviceMetrics", "!faec6f41", "no rxTime (no clock)"),
    ("x28f-L2", "self", "TELEMETRY_APP", "localStats", "!faec6f41", "no rxTime"),
    ("x28f-L35", "self", "TELEMETRY_APP", "deviceMetrics", "!faec6f41", "with rxTime"),
    ("x28f-L4", "live", "POSITION_APP", None, "!69854e34", "no rxTime, precisionBits 13"),
    ("x28f-L7", "live", "TRACEROUTE_APP", None, "!43596b18", "to the feeder, bitfield 2 (PDYb)"),
    ("x28f-L8", "self", "ROUTING_APP", None, "!faec6f41", "self ACK"),
    ("x28f-L9", "live", "ROUTING_APP", None, "!43596b18", "no hop fields"),
    ("x28f-L12", "live", "NODEINFO_APP", None, "!43596b18", "channel 1"),
    ("x28f-L25", "live", "STORE_FORWARD_APP", None, "!a35ae558", "router heartbeat"),
    ("x28f-L42", "live", "TELEMETRY_APP", "environmentMetrics", "!8ec343c3", ""),
    ("p27-L1", "self", "TELEMETRY_APP", "deviceMetrics", "!433b82f0", "PDYt (ESP32) 2.7 self telemetry"),
    ("p27-L4", "live", "POSITION_APP", None, "!f101391a", "2.7 feeder (PDYt) x 2.7 sender, 7/3; arrived over wifi (UDP multicast), not LoRa: no RSSI/SNR"),
    ("p27-L5", "live", "STORE_FORWARD_APP", None, "!a35ae558", "2.7 feeder, router heartbeat; arrived over wifi (UDP multicast), not LoRa: no RSSI/SNR"),
    ("p27-L7", "live", "NODEINFO_APP", None, "!433b10bc", "2.7 feeder (PDYt), MAC-id sender; arrived over wifi (UDP multicast), not LoRa: no RSSI/SNR"),
    ("p27-L12", "live", "TELEMETRY_APP", "deviceMetrics", "!2b6a77f6", "2.7 feeder, 6/4; arrived over wifi (UDP multicast), not LoRa: no RSSI/SNR"),
    ("p27-L19", "live", "ENCRYPTED", None, "!43596b18", "channel 68, no decoded: bot never uploads; arrived over wifi (UDP multicast), not LoRa: no RSSI/SNR"),
    ("p28-L1", "self", "TELEMETRY_APP", "deviceMetrics", "!8959691b", "PDYt (ESP32) 2.8 self telemetry"),
    ("p28-L8", "live", "NODEINFO_APP", None, "!46220165", "2.8 feeder x 2.7 sender (MAC-id)"),
    ("p28-L9", "live", "TELEMETRY_APP", "deviceMetrics", "!46220165", "2.8 feeder x 2.7 sender"),
    ("p28-L10", "live", "POSITION_APP", None, "!46220165", "2.8 feeder x 2.7 sender"),
    ("p28-L38", "replay", "POSITION_APP", None, "!46220165", "replay burst over serial on a 61-node NodeDB, 7/6"),
    ("p28-L55", "replay", "POSITION_APP", None, "!faec6f41", "replay of the Xiao's own node, hopStart == hopLimit: fake direct"),
    ("p28-L61", "replay", "TELEMETRY_APP", "deviceMetrics", "!46220165", "replay burst telemetry, 7/6"),
    ("p28s-L16", "live", "NODEINFO_APP", None, "!faec6f41", "xeddsaSigned true: the Xiao on BALANCED, 2.8 feeder x 2.8 signer"),
    ("p28s-L2", "live", "NODEINFO_APP", None, "!faec6f41", "2.8 x 2.8, unsigned unicast NodeInfo to the feeder"),
    ("p28t-L41", "live", "TRACEROUTE_APP", None, "!faec6f41", "2.8 x 2.8 traceroute from the Xiao to the feeder"),
    ("p28t-L49", "live", "POSITION_APP", None, "!faec6f41", "2.8 x 2.8 position from the Xiao, unicast to the feeder"),
    ("p28d-L55", "live", "TEXT_MESSAGE_APP", None, "!faec6f41", "text DM between our nodes, pkiEncrypted"),
    ("p28d-L58", "live", "PAGING_APP", None, "!faec6f41", "port 38 DM, pkiEncrypted"),
]


def dumps_line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write_json(path: Path, obj: Any, indent: int) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8"
    )


# --- scrubbing (needs the protobufs) -------------------------------------


def _protos():
    from meshtastic.protobuf import mesh_pb2, portnums_pb2

    return mesh_pb2, portnums_pb2


def _round_position_msg(pos) -> None:
    present = {f.name for f, _ in pos.ListFields()}
    for name in ("latitude_i", "longitude_i"):
        if name in present:
            setattr(pos, name, rules.round_i(getattr(pos, name)))


def scrub_position_bytes(data: bytes, where: str) -> bytes:
    """Round the coordinates in serialised ``Position`` bytes.

    Asserts that re-serialising the untouched message reproduces the input and
    that only the two coordinate fields differ afterwards.
    """
    mesh_pb2, _ = _protos()
    old = mesh_pb2.Position()
    old.ParseFromString(data)
    if old.SerializeToString() != data:
        raise ValueError(f"{where}: Position does not round-trip byte for byte")
    new = mesh_pb2.Position()
    new.CopyFrom(old)
    _round_position_msg(new)
    check = mesh_pb2.Position()
    check.CopyFrom(new)
    for name in ("latitude_i", "longitude_i"):
        if name in {f.name for f, _ in old.ListFields()}:
            setattr(check, name, getattr(old, name))
        else:
            check.ClearField(name)
    if check != old:
        raise ValueError(f"{where}: scrub changed more than the coordinates")
    return new.SerializeToString()


def scrub_meshpacket_b64(raw_b64: Optional[str], where: str) -> Optional[str]:
    """Round the position inside a ``MeshPacket``; other packets pass unchanged."""
    if not raw_b64:
        return raw_b64
    mesh_pb2, portnums_pb2 = _protos()
    data = base64.b64decode(raw_b64)
    mp = mesh_pb2.MeshPacket()
    mp.ParseFromString(data)
    if mp.SerializeToString() != data:
        raise ValueError(f"{where}: MeshPacket does not round-trip byte for byte")
    if not (
        mp.HasField("decoded") and mp.decoded.portnum == portnums_pb2.POSITION_APP
    ):
        return raw_b64
    mp.decoded.payload = scrub_position_bytes(bytes(mp.decoded.payload), where)
    return base64.b64encode(mp.SerializeToString()).decode("ascii")


def scrub_tree(obj: Any, where: str) -> None:
    """In place: round every coordinate and every ``Position`` payload under *obj*."""
    for d in rules.walk_dicts(obj):
        for key in rules._COORD_I:
            if key in d and isinstance(d[key], int):
                d[key] = rules.round_i(d[key])
        for key in rules._COORD_F:
            if key in d and isinstance(d[key], (int, float)):
                i = d.get(key + "I")
                if isinstance(i, int):
                    d[key] = i / 1e7
                else:
                    d[key] = rules.round_i(round(d[key] * 1e7)) / 1e7
        if d.get("portnum") == rules.POSITION_PORT and isinstance(
            d.get("payload"), str
        ):
            d["payload"] = base64.b64encode(
                scrub_position_bytes(base64.b64decode(d["payload"]), where)
            ).decode("ascii")


def drop_foreign_text(obj: Any, own: set[int]) -> int:
    """In place: remove every text packet from a node outside *own*, however nested.

    A NodeDB entry's ``lastReceived`` can be somebody's text message; the whole
    ``lastReceived`` goes (text, payload and its ``raw`` copy). Returns how many.
    """
    hits = rules.foreign_text_keys(obj, own)
    for parent, key in hits:
        parent.pop(key, None)
    return len(hits)


def drop_str_raw(obj: Any) -> Any:
    """Bot dumps carry ``raw`` as ``str(proto)``; the bot's serialiser drops it too."""
    if isinstance(obj, dict):
        return {
            k: drop_str_raw(v)
            for k, v in obj.items()
            if not (k == "raw" and isinstance(v, str))
        }
    if isinstance(obj, list):
        return [drop_str_raw(v) for v in obj]
    return obj


# --- reading inputs ------------------------------------------------------


class Source:
    def __init__(self, kind, entries, meta, nodedb):
        self.kind = kind  # "fx1_capture" | "bot_dump"
        self.entries = entries  # [{"t_host","raw_b64","packet","folder_kind"}]
        self.meta = meta  # {"feeder_num","feeder_fw","hw_model","device_state_version","lib"}
        self.nodedb = nodedb


def read_fx1(path: Path) -> Source:
    stem = path.with_suffix("")
    meta_raw = json.loads(Path(f"{stem}_meta.json").read_text(encoding="utf-8"))
    nodedb = json.loads(Path(f"{stem}_nodedb.json").read_text(encoding="utf-8"))
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            entries.append(
                {
                    "t_host": rec["t_host"],
                    "raw_b64": rec.get("raw_b64"),
                    "packet": rec["packet"],
                    "folder_kind": None,
                }
            )
    my_info = meta_raw.get("my_info", {})
    metadata = meta_raw.get("metadata", {})
    meta = {
        "feeder_num": my_info.get("myNodeNum"),
        "feeder_fw": metadata.get("firmwareVersion"),
        "hw_model": metadata.get("hwModel"),
        "device_state_version": metadata.get("deviceStateVersion"),
        "lib": meta_raw.get("lib"),
    }
    return Source("fx1_capture", entries, meta, nodedb)


def read_dump(root: Path) -> Source:
    packets_dir = root / "packets"
    entries = []
    for folder, folder_kind in ((packets_dir, None), (root / "replay", "replay")):
        if not folder.is_dir():
            continue
        for port_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
            if port_dir.name.startswith("_"):
                continue
            for f in sorted(port_dir.glob("*.json")):
                rec = json.loads(f.read_text(encoding="utf-8"))
                captured = datetime.fromisoformat(rec["meta"]["captured_at"])
                entries.append(
                    {
                        "t_host": captured.timestamp(),
                        "raw_b64": rec.get("raw_b64"),
                        "packet": drop_str_raw(rec["packet"]),
                        "folder_kind": folder_kind,
                        "meta": rec["meta"],
                        "name": f.name,
                    }
                )
    if not entries:
        raise SystemExit(f"{root}: no packets/<PORT>/*.json or replay/<PORT>/*.json")
    entries.sort(key=lambda e: (e["t_host"], e["name"]))
    first = entries[0]["meta"]
    nodedb_files = sorted((packets_dir / "_nodedb").glob("*.json")) or sorted(
        (root / "_nodedb").glob("*.json")
    )
    nodedb = (
        json.loads(nodedb_files[-1].read_text(encoding="utf-8")) if nodedb_files else {}
    )
    meta = {
        "feeder_num": first.get("feeder_num"),
        "feeder_fw": first.get("feeder_fw"),
        "hw_model": None,
        "device_state_version": None,
        "lib": first.get("lib_version"),
    }
    return Source("bot_dump", entries, meta, nodedb)


# --- building ------------------------------------------------------------


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_node(value: str) -> int:
    return int(value[1:], 16) if value.startswith("!") else int(value)


def build_records(src: Source, own_nodes: set[int]) -> list[dict]:
    feeder = src.meta["feeder_num"]
    own = set(own_nodes) | {feeder}
    records = []
    for entry in src.entries:
        packet = json.loads(json.dumps(entry["packet"]))  # deep copy
        decoded = packet.get("decoded") or {}
        if decoded.get("portnum") == "TEXT_MESSAGE_APP" and packet.get("from") not in own:
            continue  # other people's text is never kept
        records.append(
            {
                "src_line": len(records) + 1,
                "t_host": entry["t_host"],
                "raw_b64": entry["raw_b64"],
                "packet": packet,
                "kind": entry["folder_kind"] or rules.classify_kind(packet, feeder),
            }
        )
    for rec in records:
        where = f"line {rec['src_line']}"
        scrub_tree(rec["packet"], where)
        rec["raw_b64"] = scrub_meshpacket_b64(rec["raw_b64"], where)
        expected = rules.classify_kind(rec["packet"], feeder)
        if rec["kind"] != expected:
            raise SystemExit(
                f"{where}: input says {rec['kind']} but the replay rule says {expected}"
            )
    return records


def build_manifest(
    src: Source, records: list[dict], nodedb: dict, args: argparse.Namespace
) -> dict:
    meta = src.meta
    feeder = meta["feeder_num"]
    derived = rules.recount(records, nodedb, feeder)
    own = sorted(rules.node_id_str(parse_node(v)) for v in (args.own_node or []))
    manifest = {
        "capture_id": args.capture_id,
        "short": args.short or args.capture_id,
        "source": src.kind,
        "feeder": {
            "num": feeder,
            "id": rules.node_id_str(feeder),
            "firmware": meta["feeder_fw"],
            "hw_model": args.hw_model or meta["hw_model"],
            "device_state_version": meta["device_state_version"],
            "hop_limit": args.hop_limit,
            "role": args.role,
            "signature_policy": args.signature_policy,
        },
        "lib": {
            "name": "meshtastic-python",
            "note": args.lib_note or f"reports {meta['lib']}",
        },
        "start": iso(records[0]["t_host"]),
        "end": iso(records[-1]["t_host"]),
        "duration_s": round(records[-1]["t_host"] - records[0]["t_host"]),
        "counts": derived["counts"],
        "senders": derived["senders"],
        "self_telemetry": derived["self_telemetry"],
        "replay_burst": {**derived["replay_burst"], "stable_ids_shared_with": []},
        "scrub": {**BASE_SCRUB, **derived["scrub_positions"]},
        "notes": args.notes or "",
    }
    if own:
        # Test nodes whose text messages may be kept (the checker allows exactly these).
        manifest["own_nodes"] = own
    return manifest


def link_replay_ids(captures_dir: Path) -> None:
    """Fill ``replay_burst.stable_ids_shared_with`` in every manifest, both ways."""
    ids: dict[str, set[int]] = {}
    for d in sorted(p for p in captures_dir.iterdir() if (p / "capture.jsonl").is_file()):
        records = load_capture_records(d)
        ids[d.name] = rules.replay_ids(records)
    for name in ids:
        mpath = captures_dir / name / "manifest.json"
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        shared = sorted(o for o in ids if o != name and ids[name] & ids[o])
        manifest["replay_burst"]["stable_ids_shared_with"] = shared
        write_json(mpath, manifest, 2)


def load_capture_records(capture_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (capture_dir / "capture.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build(args: argparse.Namespace) -> None:
    src_path = Path(args.input)
    src = read_dump(src_path) if src_path.is_dir() else read_fx1(src_path)
    own = {parse_node(v) for v in (args.own_node or [])}
    records = build_records(src, own)

    nodedb = json.loads(json.dumps(src.nodedb))
    drop_foreign_text(nodedb, own | {src.meta["feeder_num"]})
    scrub_tree(nodedb, "nodedb")
    for what, obj in (("records", [r["packet"] for r in records]), ("nodedb", nodedb)):
        bad = rules.secret_keys(obj)
        if bad:
            raise SystemExit(f"{what}: refusing to write secret-looking keys {bad}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "capture.jsonl").write_text(
        "".join(dumps_line(r) + "\n" for r in records), encoding="utf-8"
    )
    write_json(out / "nodedb.json", nodedb, 1)
    write_json(out / "manifest.json", build_manifest(src, records, nodedb, args), 2)
    link_replay_ids(out.parent)
    print(f"{args.capture_id}: {len(records)} records -> {out}")


# --- subset --------------------------------------------------------------


def build_subset(root: Path) -> list[dict]:
    index = json.loads((root / "captures.json").read_text(encoding="utf-8"))
    by_short = {e["short"]: e for e in index if e.get("status") == "captured"}
    loaded: dict[str, dict] = {}
    for short, entry in by_short.items():
        d = root / entry["path"]
        loaded[short] = {
            "manifest": json.loads((d / "manifest.json").read_text(encoding="utf-8")),
            "records": load_capture_records(d),
            "nodedb": json.loads((d / "nodedb.json").read_text(encoding="utf-8")),
        }
    stable = {
        (s, i)
        for s, c in loaded.items()
        for i in rules.replay_ids(c["records"])
        if any(
            i in rules.replay_ids(o["records"]) for t, o in loaded.items() if t != s
        )
    }
    out, problems = [], []
    for key, kind, port, variant, sender, _why in SUBSET:
        short, line = key.rsplit("-L", 1)
        cap = loaded[short]
        rec = cap["records"][int(line) - 1]
        packet = rec["packet"]
        got = (
            rec["kind"],
            rules.port_of(packet),
            rules.telemetry_variant(packet) if port == "TELEMETRY_APP" else None,
            rules.node_id_str(packet["from"]),
        )
        if rec["src_line"] != int(line) or got != (kind, port, variant, sender):
            problems.append(f"{key}: expected {(kind, port, variant, sender)}, got {got}")
            continue
        manifest = cap["manifest"]
        feeder = manifest["feeder"]
        schemes = rules.sender_schemes(cap["records"], cap["nodedb"], feeder["num"])
        out.append(
            {
                "key": key,
                "capture": short,
                "src_line": rec["src_line"],
                "id": packet["id"],
                "from": sender,
                "kind": kind,
                "port": port,
                "variant": variant,
                "labels": rules.labels_for(
                    rec,
                    feeder_fw=feeder["firmware"],
                    scheme=schemes[packet["from"]],
                    stable_replay=(short, packet["id"]) in stable and kind == "replay",
                    pki_label=short not in FROZEN_SHORTS,
                    transport_label=short not in FROZEN_SHORTS,
                ),
                "feeder_num": feeder["num"],
                "t_host": rec["t_host"],
                "record": {"raw_b64": rec["raw_b64"], "packet": packet},
            }
        )
    if problems:
        raise SystemExit("subset rows that do not match their line:\n" + "\n".join(problems))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", nargs="?", help="fx1 <stem>.jsonl or a bot dump directory")
    ap.add_argument("--capture-id")
    ap.add_argument("--short", help="short key used in subset keys (x28, ...)")
    ap.add_argument("--out", help="capture directory to write")
    ap.add_argument("--hop-limit", type=int)
    ap.add_argument("--role")
    ap.add_argument("--signature-policy")
    ap.add_argument("--hw-model")
    ap.add_argument("--lib-note", help="how the capturing lib is described in the manifest")
    ap.add_argument("--notes", help="free text for the manifest")
    ap.add_argument(
        "--own-node",
        action="append",
        help="a test node whose TEXT_MESSAGE_APP packets may be kept (repeatable)",
    )
    ap.add_argument("--subset", metavar="ROOT", help="rebuild ROOT/subset.json instead")
    args = ap.parse_args(argv)

    if args.subset:
        root = Path(args.subset)
        write_json(root / "subset.json", build_subset(root), 1)
        print(f"{root / 'subset.json'}: {len(SUBSET)} entries")
        return 0
    if not (args.input and args.capture_id and args.out):
        ap.error("input, --capture-id and --out are required")
    build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
