"""Tests for MeshCore storage upload path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api.StorageAPI import MESHCORE_FEEDER_PUBKEY_HEADER, StorageAPIWrapper
from src.meshcore.serializers import MeshCorePacketSerializer

FEEDER_PREFIX = "1a37f5aea4a1"
FEEDER_PUBKEY = FEEDER_PREFIX + ("b" * 52)


def _meshcore_wrapper(**kwargs) -> StorageAPIWrapper:
    defaults = {
        "base_url": "http://api.test",
        "token": "secret",
        "api_version": 2,
        "serializer": MeshCorePacketSerializer(),
        "local_meshtastic_nodenum_provider": lambda: None,
        "meshcore_feeder_prefix_provider": lambda: FEEDER_PREFIX,
        "meshcore_feeder_pubkey_provider": lambda: FEEDER_PUBKEY,
    }
    defaults.update(kwargs)
    return StorageAPIWrapper(**defaults)


def test_store_raw_meshcore_packet_posts_to_feeder_ingest() -> None:
    wrapper = _meshcore_wrapper()
    envelope = {
        "meshcore": True,
        "type": "advertisement",
        "payload": {"public_key": FEEDER_PUBKEY, "recv_time": 1730000000},
        "attributes": {},
    }
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "success", "packet_id": "uuid"}
    with patch.object(wrapper, "_post", return_value=mock_response) as post:
        result = wrapper.store_raw_meshcore_packet(envelope)
    assert result["status"] == "success"
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == f"/api/meshcore/feeders/{FEEDER_PREFIX}/packets/ingest/"
    assert kwargs["json"]["payload_type"] == "advert"
    assert wrapper._get_headers()[MESHCORE_FEEDER_PUBKEY_HEADER] == FEEDER_PUBKEY


def test_post_mc_channel_sync_success() -> None:
    wrapper = _meshcore_wrapper()
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch.object(wrapper, "_post", return_value=mock_response) as post:
        ok = wrapper.post_mc_channel_sync(
            {"channels": [], "synced_at": "2026-01-01T00:00:00Z"}
        )
    assert ok is True
    post.assert_called_once_with(
        f"/api/meshcore/feeders/{FEEDER_PREFIX}/mc-channel-sync/",
        json={"channels": [], "synced_at": "2026-01-01T00:00:00Z"},
    )


def test_post_mc_channel_sync_http_error_returns_false() -> None:
    from requests import HTTPError

    wrapper = _meshcore_wrapper()
    response = MagicMock()
    response.text = "bad"
    with patch.object(wrapper, "_post", side_effect=HTTPError(response=response)):
        assert wrapper.post_mc_channel_sync({"channels": []}) is False


def test_report_bot_version_uses_meshcore_feeder_path() -> None:
    wrapper = _meshcore_wrapper()
    mock_response = MagicMock()
    with patch.object(wrapper, "_put", return_value=mock_response) as put:
        assert wrapper.report_bot_version() is True
    assert put.call_args[0][0] == f"/api/meshcore/feeders/{FEEDER_PREFIX}/bot-version/"
    assert wrapper._get_headers()[MESHCORE_FEEDER_PUBKEY_HEADER] == FEEDER_PUBKEY
