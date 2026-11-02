"""Tests for :mod:`src.persistence.packet_dump`."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from meshtastic.protobuf import mesh_pb2, portnums_pb2

import src.persistence.packet_dump as packet_dump


def _only_file(directory: Path) -> dict:
    files = list(directory.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def _packet_with_unknown_fields() -> mesh_pb2.MeshPacket:
    """A MeshPacket carrying a field (tag 22, bytes) this lib does not know."""
    pkt = mesh_pb2.MeshPacket()
    setattr(pkt, "from", 123)
    pkt.to = 456
    pkt.id = 789
    pkt.decoded.portnum = portnums_pb2.TEXT_MESSAGE_APP
    pkt.decoded.payload = b"hi"
    # tag 22, wire type 2 (length-delimited): key = (22 << 3) | 2 = 178 -> 0xB2 0x01
    unknown = b"\xb2\x01\x04\xde\xad\xbe\xef"
    pkt.MergeFromString(pkt.SerializeToString() + unknown)
    return pkt


def test_dump_packet_noop_when_portnums_unset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", None)
    packet_dump.dump_packet(
        {"decoded": {"portnum": "TEXT_MESSAGE_APP"}}, data_dir=tmp_path
    )
    assert not (tmp_path / "packets").exists()


def test_dump_packet_writes_record_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", ["TEXT_MESSAGE_APP"])
    packet = {"decoded": {"portnum": "TEXT_MESSAGE_APP"}, "id": 1}
    packet_dump.dump_packet(
        packet, feeder_num=42, feeder_fw="2.7.11", data_dir=tmp_path
    )
    rec = _only_file(tmp_path / "packets" / "TEXT_MESSAGE_APP")
    assert set(rec) == {"packet", "raw_b64", "meta"}
    assert rec["packet"]["id"] == 1
    assert rec["raw_b64"] is None
    assert set(rec["meta"]) == {
        "feeder_num",
        "feeder_fw",
        "lib_version",
        "captured_at",
    }
    assert rec["meta"]["feeder_num"] == 42
    assert rec["meta"]["feeder_fw"] == "2.7.11"
    assert rec["meta"]["lib_version"]
    assert rec["meta"]["captured_at"]


def test_dump_packet_feeder_fw_may_be_null(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", ["*"])
    packet_dump.dump_packet({"decoded": {"portnum": "X"}}, data_dir=tmp_path)
    rec = _only_file(tmp_path / "packets" / "X")
    assert rec["meta"]["feeder_fw"] is None
    assert rec["meta"]["feeder_num"] is None


def test_raw_b64_round_trips_and_preserves_unknown_fields(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", ["TEXT_MESSAGE_APP"])
    pkt = _packet_with_unknown_fields()
    assert pkt.SerializeToString().endswith(b"\xde\xad\xbe\xef")  # sanity

    packet_dump.dump_packet(
        {"decoded": {"portnum": "TEXT_MESSAGE_APP"}, "raw": pkt}, data_dir=tmp_path
    )
    rec = _only_file(tmp_path / "packets" / "TEXT_MESSAGE_APP")

    restored = mesh_pb2.MeshPacket()
    restored.ParseFromString(base64.b64decode(rec["raw_b64"]))
    assert restored.id == 789
    assert restored.decoded.payload == b"hi"
    assert restored.SerializeToString() == pkt.SerializeToString()
    assert restored.SerializeToString().endswith(b"\xb2\x01\x04\xde\xad\xbe\xef")
    # the protobuf object is not stringified into the packet dict
    assert "raw" not in rec["packet"]


def test_bytes_values_are_base64_not_repr(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", ["*"])
    packet = {
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"\x00\xffhi"},
        "nested": [{"k": b"\x01\x02"}],
        "publicKey": b"\xaa" * 4,
    }
    packet_dump.dump_packet(packet, data_dir=tmp_path)
    rec = _only_file(tmp_path / "packets" / "TEXT_MESSAGE_APP")["packet"]
    assert rec["decoded"]["payload"] == base64.b64encode(b"\x00\xffhi").decode()
    assert rec["nested"][0]["k"] == base64.b64encode(b"\x01\x02").decode()
    assert rec["publicKey"] == base64.b64encode(b"\xaa" * 4).decode()
    assert "b'" not in json.dumps(rec)


def test_dump_packet_honours_data_dir_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", ["*"])
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "custom"))
    monkeypatch.chdir(tmp_path)
    packet_dump.dump_packet({"decoded": {"portnum": "NODEINFO_APP"}})
    assert list((tmp_path / "custom" / "packets" / "NODEINFO_APP").glob("*.json"))
    assert not (tmp_path / "data").exists()


def test_resolve_data_dir_default_is_repo_data(monkeypatch) -> None:
    monkeypatch.delenv("DATA_DIR", raising=False)
    path = packet_dump.resolve_data_dir()
    assert path.name == "data"
    assert (path.parent / "src").is_dir()


def test_dump_packet_skips_unlisted_portnum(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_portnums", ["TEXT_MESSAGE_APP"])
    packet_dump.dump_packet(
        {"decoded": {"portnum": "POSITION_APP"}}, data_dir=tmp_path
    )
    assert not (tmp_path / "packets" / "POSITION_APP").exists()


def test_dump_nodes_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_nodedb", False)
    assert packet_dump.dump_nodes({"!1": {"num": 1}}, data_dir=tmp_path) is None
    assert not (tmp_path / "packets").exists()


def test_dump_nodes_writes_base64(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_nodedb", True)
    nodes = {"!0000007b": {"num": 123, "user": {"publicKey": b"\x01\x02\x03"}}}
    path = packet_dump.dump_nodes(nodes, data_dir=tmp_path)
    assert path is not None and path.parent == tmp_path / "packets" / "_nodedb"
    data = json.loads(path.read_text())
    assert data["!0000007b"]["user"]["publicKey"] == base64.b64encode(
        b"\x01\x02\x03"
    ).decode()
    assert data["!0000007b"]["num"] == 123


def test_dump_nodes_honours_data_dir_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_nodedb", True)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "custom"))
    assert packet_dump.dump_nodes({"!1": {"num": 1}}) is not None
    assert list((tmp_path / "custom" / "packets" / "_nodedb").glob("*.json"))


def test_dump_nodes_empty_is_noop(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packet_dump, "dump_nodedb", True)
    assert packet_dump.dump_nodes({}, data_dir=tmp_path) is None
    assert packet_dump.dump_nodes(None, data_dir=tmp_path) is None
