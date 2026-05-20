"""Tests for :mod:`src.persistence.packet_dump`."""

from __future__ import annotations

import json
from pathlib import Path

import src.persistence.packet_dump as packet_dump


def test_dump_packet_noop_when_portnums_unset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(packet_dump, "dump_portnums", None)
    packet_dump.dump_packet({"decoded": {"portnum": "TEXT_MESSAGE_APP"}})
    assert not (tmp_path / "data").exists()


def test_dump_packet_writes_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(packet_dump, "dump_portnums", ["TEXT_MESSAGE_APP"])
    packet = {"decoded": {"portnum": "TEXT_MESSAGE_APP"}, "id": 1}
    packet_dump.dump_packet(packet)
    out_dir = tmp_path / "data" / "packets" / "TEXT_MESSAGE_APP"
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["id"] == 1


def test_dump_packet_wildcard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(packet_dump, "dump_portnums", ["*"])
    packet_dump.dump_packet({"decoded": {"portnum": "NODEINFO_APP"}})
    assert list((tmp_path / "data" / "packets" / "NODEINFO_APP").glob("*.json"))


def test_dump_packet_skips_unlisted_portnum(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(packet_dump, "dump_portnums", ["TEXT_MESSAGE_APP"])
    packet_dump.dump_packet({"decoded": {"portnum": "POSITION_APP"}})
    assert not (tmp_path / "data" / "packets" / "POSITION_APP").exists()
