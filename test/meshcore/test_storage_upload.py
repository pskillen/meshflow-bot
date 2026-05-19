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
