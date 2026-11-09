#!/usr/bin/env python3
"""Verify the committed Meshtastic packet fixtures.

    python tools/meshtastic_fixtures/check_fixtures.py docs/meshtastic_packets/2.8

Prints one ``OK`` line per capture and exits 0, or prints every problem (file
and line first) and exits 1. Checks, per ``captured`` entry in ``captures.json``:

* ``manifest.json``, ``capture.jsonl`` and ``nodedb.json`` exist; the manifest's
  counts equal a recount of the records;
* every record's ``kind`` follows the replay rule, and ``src.meshtastic.replay.
  is_replayed`` agrees (when the repo's ``src`` package imports);
* every position (packet dict, ``raw`` copies, NodeDB) is on the 0.1 deg grid;
  with ``google.protobuf`` and ``meshtastic`` installed, ``decoded.payload`` and
  ``raw_b64`` decode to the same rounded position as the dict;
* no key looks like key material, a config secret or a ``deviceId``;
* ``subset.json`` keys are unique, well formed, and each embedded record equals
  its capture line.

``pending`` entries have no directory and are skipped. The non-protobuf half uses
only the standard library.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.meshtastic_fixtures import rules  # noqa: E402


class Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, where: str, message: str) -> None:
        self.items.append(f"{where}: {message}")


def _read_json(path: Path, problems: Problems) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.add(str(path), "missing")
    except ValueError as exc:
        problems.add(str(path), f"not valid JSON ({exc})")
    return None


def _read_records(path: Path, problems: Problems) -> Optional[list[dict]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        problems.add(str(path), "missing")
        return None
    records = []
    for n, line in enumerate(text.splitlines(), 1):
        try:
            records.append(json.loads(line))
        except ValueError as exc:
            problems.add(f"{path}:{n}", f"not valid JSON ({exc})")
            return None
    return records


# --- optional pieces -----------------------------------------------------


def _is_replayed():
    try:
        from src.meshtastic.replay import is_replayed

        return is_replayed
    except Exception:  # pragma: no cover - src not importable
        return None


def _protos():
    try:
        from meshtastic.protobuf import mesh_pb2, portnums_pb2

        return mesh_pb2, portnums_pb2
    except Exception:  # pragma: no cover - lib not installed
        return None


def _position_xy(pos) -> tuple[int, int]:
    return pos.latitude_i, pos.longitude_i


def _dict_xy(position: dict) -> tuple[int, int]:
    return position.get("latitudeI", 0), position.get("longitudeI", 0)


def check_protobuf(rec: dict, where: str, problems: Problems) -> None:
    protos = _protos()
    if protos is None:
        return
    mesh_pb2, portnums_pb2 = protos
    from google.protobuf.message import DecodeError

    packet = rec["packet"]
    decoded = packet.get("decoded") or {}
    if decoded.get("portnum") != rules.POSITION_PORT:
        return
    expect = _dict_xy(decoded.get("position") or {})

    try:
        pos = mesh_pb2.Position()
        pos.ParseFromString(base64.b64decode(decoded.get("payload", "")))
        if _position_xy(pos) != expect:
            problems.add(where, f"decoded.payload position {_position_xy(pos)} != dict {expect}")
    except (DecodeError, ValueError) as exc:
        problems.add(where, f"decoded.payload is not a valid Position: {exc}")

    if rec.get("raw_b64"):
        try:
            mp = mesh_pb2.MeshPacket()
            mp.ParseFromString(base64.b64decode(rec["raw_b64"]))
            inner = mesh_pb2.Position()
            inner.ParseFromString(bytes(mp.decoded.payload))
            if _position_xy(inner) != expect:
                problems.add(where, f"raw_b64 position {_position_xy(inner)} != dict {expect}")
        except (DecodeError, ValueError) as exc:
            problems.add(where, f"raw_b64 is not a valid MeshPacket: {exc}")


# --- checks --------------------------------------------------------------


def check_capture(
    root: Path, entry: dict, problems: Problems, is_replayed
) -> Optional[tuple[dict, list[dict], dict]]:
    cdir = root / entry["path"]
    manifest = _read_json(cdir / "manifest.json", problems)
    records = _read_records(cdir / "capture.jsonl", problems)
    nodedb = _read_json(cdir / "nodedb.json", problems)
    if manifest is None or records is None or nodedb is None:
        return None
    feeder = manifest["feeder"]["num"]
    own = {int(v[1:], 16) for v in manifest.get("own_nodes", [])} | {feeder}
    log = cdir / "capture.jsonl"

    for n, rec in enumerate(records, 1):
        where = f"{log}:{n}"
        if rec.get("src_line") != n:
            problems.add(where, f"src_line is {rec.get('src_line')}, expected {n}")
        expected = rules.classify_kind(rec["packet"], feeder)
        if rec.get("kind") != expected:
            problems.add(where, f"kind {rec.get('kind')!r} but the replay rule says {expected!r}")
        if is_replayed is not None:
            classifier = is_replayed(rec["packet"], feeder)
            if classifier != (rec.get("kind") == "replay"):
                problems.add(
                    where,
                    f"src.meshtastic.replay.is_replayed says {classifier} for a {rec.get('kind')} record",
                )
        bad = rules.grid_violations(rec["packet"])
        if bad:
            problems.add(where, "position off the 0.1 deg grid: " + ", ".join(bad))
        check_protobuf(rec, where, problems)
        leaked = rules.secret_keys(rec["packet"])
        if leaked:
            problems.add(where, f"secret-looking keys {leaked}")
        if (
            (rec["packet"].get("decoded") or {}).get("portnum") == "TEXT_MESSAGE_APP"
            and rec["packet"].get("from") not in own
        ):
            problems.add(where, "text message from a node that is not the feeder or a listed own node")

    for _parent, key in rules.foreign_text_keys(nodedb, own):
        problems.add(
            str(cdir / "nodedb.json"),
            f"text message from a node that is not the feeder or a listed own node (under {key!r})",
        )

    bad = rules.grid_violations(nodedb)
    if bad:
        problems.add(str(cdir / "nodedb.json"), "position off the 0.1 deg grid: " + ", ".join(bad[:5]))
    for d in rules.walk_dicts(nodedb):
        if d.get("portnum") == rules.POSITION_PORT and isinstance(d.get("payload"), str):
            check_protobuf({"packet": {"decoded": d}, "raw_b64": None}, str(cdir / "nodedb.json"), problems)
    for name, obj in (("nodedb.json", nodedb), ("manifest.json", manifest)):
        leaked = rules.secret_keys(obj)
        if leaked:
            problems.add(str(cdir / name), f"secret-looking keys {leaked}")

    derived = rules.recount(records, nodedb, feeder)
    for section in ("counts", "senders", "self_telemetry"):
        if manifest.get(section) != derived[section]:
            problems.add(
                str(cdir / "manifest.json"),
                f"{section} differ from a recount: manifest {manifest.get(section)} vs {derived[section]}",
            )
    burst = {k: v for k, v in manifest.get("replay_burst", {}).items() if k != "stable_ids_shared_with"}
    if burst != derived["replay_burst"]:
        problems.add(str(cdir / "manifest.json"), f"replay_burst differs from a recount: {burst} vs {derived['replay_burst']}")
    scrub = {k: v for k, v in manifest.get("scrub", {}).items() if k != "rule"}
    if scrub != derived["scrub_positions"]:
        problems.add(str(cdir / "manifest.json"), f"scrub counts differ from a recount: {scrub} vs {derived['scrub_positions']}")
    if records:
        if abs(manifest["duration_s"] - (records[-1]["t_host"] - records[0]["t_host"])) > 1:
            problems.add(str(cdir / "manifest.json"), "duration_s does not match the records")
    return manifest, records, nodedb


def check_stable_ids(loaded: dict[str, tuple[dict, list[dict], dict]], problems: Problems) -> None:
    ids = {cid: rules.replay_ids(recs) for cid, (_, recs, _) in loaded.items()}
    for cid, (manifest, _, _) in loaded.items():
        expected = sorted(o for o in ids if o != cid and ids[cid] & ids[o])
        got = manifest.get("replay_burst", {}).get("stable_ids_shared_with")
        if got != expected:
            problems.add(f"{cid}/manifest.json", f"stable_ids_shared_with is {got}, expected {expected}")


def check_subset(root: Path, shorts: dict[str, list[dict]], problems: Problems) -> int:
    path = root / "subset.json"
    subset = _read_json(path, problems)
    if subset is None:
        return 0
    key_re = re.compile(r"^(" + "|".join(re.escape(s) for s in shorts) + r")-L\d+$")
    seen: set[str] = set()
    for n, entry in enumerate(subset):
        key = entry.get("key", f"#{n}")
        where = f"{path} [{key}]"
        if key in seen:
            problems.add(where, "duplicate key")
        seen.add(key)
        if not key_re.match(key):
            problems.add(where, "key does not match <capture short>-L<line>")
            continue
        short, line = key.rsplit("-L", 1)
        records = shorts[short]
        if not 1 <= int(line) <= len(records):
            problems.add(where, f"line {line} is outside the capture")
            continue
        rec = records[int(line) - 1]
        if entry.get("record") != {"raw_b64": rec["raw_b64"], "packet": rec["packet"]}:
            problems.add(where, f"embedded record differs from {short} line {line}")
        for field, value in (
            ("capture", short),
            ("src_line", int(line)),
            ("id", rec["packet"].get("id")),
            ("from", rules.node_id_str(rec["packet"]["from"])),
            ("kind", rec["kind"]),
            ("port", rules.port_of(rec["packet"])),
            ("t_host", rec["t_host"]),
        ):
            if entry.get(field) != value:
                problems.add(where, f"{field} is {entry.get(field)!r}, the capture line says {value!r}")
        for tag in ("kind", "port"):
            if f"{tag}:{entry.get(tag)}" not in entry.get("labels", []):
                problems.add(where, f"missing label {tag}:{entry.get(tag)}")
        leaked = rules.secret_keys(entry)
        if leaked:
            problems.add(where, f"secret-looking keys {leaked}")
    return len(subset)


def check_identity(root: Path, problems: Problems) -> None:
    for path in sorted((root / "identity").glob("*.json")):
        data = _read_json(path, problems)
        leaked = rules.secret_keys(data) if data is not None else []
        if leaked:
            problems.add(str(path), f"secret-looking keys {leaked}")


def check_tree(root: Path) -> tuple[list[str], list[str]]:
    """Returns (OK lines, problems)."""
    problems = Problems()
    ok: list[str] = []
    index = _read_json(root / "captures.json", problems)
    if index is None:
        return ok, problems.items
    is_replayed = _is_replayed()
    loaded: dict[str, tuple[dict, list[dict], dict]] = {}
    shorts: dict[str, list[dict]] = {}
    for entry in index:
        status = entry.get("status")
        if status == "pending":
            continue
        if status != "captured":
            problems.add("captures.json", f"{entry.get('id')}: unknown status {status!r}")
            continue
        result = check_capture(root, entry, problems, is_replayed)
        if result is None:
            continue
        manifest, records, nodedb = result
        loaded[entry["id"]] = result
        shorts[entry["short"]] = records
        c = manifest["counts"]
        ok.append(
            f"OK {entry['id']}: {c['total']} records "
            + ", ".join(f"{k} {v}" for k, v in c["by_kind"].items())
        )
    check_stable_ids(loaded, problems)
    n = check_subset(root, shorts, problems)
    check_identity(root, problems)
    leaked = rules.secret_keys(index)
    if leaked:
        problems.add("captures.json", f"secret-looking keys {leaked}")
    if not problems.items:
        ok.append(f"OK subset.json: {n} entries")
    return ok, problems.items


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    ok, problems = check_tree(Path(argv[0]))
    for line in ok:
        print(line)
    for line in problems:
        print("FAIL " + line)
    if problems:
        print(f"{len(problems)} problem(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
