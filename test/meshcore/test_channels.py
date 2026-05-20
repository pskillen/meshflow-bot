"""Unit tests for MeshCore channel snapshot helpers."""

from src.meshcore.channels import _channel_entry_from_info, snapshot_sync_body


def test_channel_entry_public():
    entry = _channel_entry_from_info(0, {"channel_name": "Public"})
    assert entry["mc_channel_type"] == "PUBLIC"
    assert entry["mc_hashtag"] is None


def test_channel_entry_hashtag():
    entry = _channel_entry_from_info(1, {"channel_name": "#galloway"})
    assert entry["mc_channel_type"] == "HASHTAG"
    assert entry["mc_hashtag"] == "galloway"


def test_snapshot_sync_body():
    body = snapshot_sync_body(
        [{"mc_channel_idx": 0, "name": "X", "mc_channel_type": "PUBLIC"}]
    )
    assert "synced_at" in body
    assert len(body["channels"]) == 1
