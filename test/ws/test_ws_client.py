"""Tests for MeshflowWSClient WebSocket URL construction."""

from src.ws_client import MeshflowWSClient


def test_ws_endpoint_includes_feeder_node_id():
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="test-key",
        on_traceroute=lambda _target: None,
        feeder_node_id_provider=lambda: 1127973616,
    )
    endpoint = client._get_ws_endpoint()
    assert (
        endpoint
        == "ws://localhost:8000/ws/nodes/?api_key=test-key&feeder_node_id=1127973616"
    )


def test_ws_endpoint_includes_feeder_pubkey_prefix():
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="test-key",
        on_traceroute=lambda _target: None,
        feeder_pubkey_prefix_provider=lambda: "1a37f5aea4a1",
    )
    endpoint = client._get_ws_endpoint()
    assert "feeder_pubkey_prefix=1a37f5aea4a1" in endpoint
    assert "feeder_node_id=" not in endpoint


def test_ws_endpoint_api_key_only_when_no_providers():
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="test-key",
        on_traceroute=lambda _target: None,
    )
    assert client._get_ws_endpoint() == "ws://localhost:8000/ws/nodes/?api_key=test-key"
