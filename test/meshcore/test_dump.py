"""Tests for :mod:`src.meshcore.dump`."""

from __future__ import annotations

import json
from pathlib import Path

from src.meshcore.dump import dump_meshcore_event


def test_dump_meshcore_event_writes_protocol_marker(tmp_path: Path) -> None:
    path = dump_meshcore_event(
        event_type="contact_message",
        payload={"text": "hi", "pubkey_prefix": "aabbccddeeff"},
        attributes={"txt_type": 1},
        base_dir=tmp_path,
    )
    assert path is not None
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["protocol"] == "meshcore"
    assert data["event_type"] == "contact_message"
    assert data["payload"]["pubkey_prefix"] == "aabbccddeeff"
