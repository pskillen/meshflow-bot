"""Tests for MeshCore storage upload path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api.StorageAPI import StorageAPIWrapper
from src.meshcore.serializers import MeshCorePacketSerializer


def test_store_raw_meshcore_packet_posts_to_ingest() -> None:
    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshCorePacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: None,
    )
    envelope = {
        "meshcore": True,
        "type": "advertisement",
        "payload": {"public_key": "a" * 64, "recv_time": 1730000000},
        "attributes": {},
    }
    mock_response = MagicMock()
    mock_response.json.return_value = {"status": "success", "packet_id": "uuid"}
    with patch.object(wrapper, "_post", return_value=mock_response) as post:
        result = wrapper.store_raw_meshcore_packet(envelope)
    assert result["status"] == "success"
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "/api/meshcore/packets/ingest/"
    assert kwargs["json"]["payload_type"] == "advert"


def test_post_mc_channel_sync_success() -> None:
    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshCorePacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: None,
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch.object(wrapper, "_post", return_value=mock_response) as post:
        ok = wrapper.post_mc_channel_sync(
            {"channels": [], "synced_at": "2026-01-01T00:00:00Z"}
        )
    assert ok is True
    post.assert_called_once_with(
        "/api/meshcore/feeder/mc-channel-sync/",
        json={"channels": [], "synced_at": "2026-01-01T00:00:00Z"},
    )


def test_post_mc_channel_sync_http_error_returns_false() -> None:
    from requests import HTTPError

    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshCorePacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: None,
    )
    response = MagicMock()
    response.text = "bad"
    with patch.object(wrapper, "_post", side_effect=HTTPError(response=response)):
        assert wrapper.post_mc_channel_sync({"channels": []}) is False
