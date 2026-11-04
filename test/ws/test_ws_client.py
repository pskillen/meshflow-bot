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


def test_reconnect_is_a_noop_when_not_connected():
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="k",
        on_traceroute=lambda _t: None,
    )
    client.reconnect()  # not started: nothing to close, must not raise


def test_reconnect_closes_live_connection_so_loop_rebuilds_endpoint():
    import asyncio
    from unittest.mock import MagicMock, patch

    nodenum = {"value": 1}
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="k",
        on_traceroute=lambda _t: None,
        feeder_node_id_provider=lambda: nodenum["value"],
    )
    client._running = True
    client._loop = MagicMock()
    client._ws = MagicMock()
    with patch.object(asyncio, "run_coroutine_threadsafe") as run:
        client.reconnect()
    run.assert_called_once()
    # the endpoint the loop builds next uses the new number
    nodenum["value"] = 2
    assert client._get_ws_endpoint().endswith("feeder_node_id=2")


def test_ws_endpoint_api_key_only_when_no_providers():
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="test-key",
        on_traceroute=lambda _target: None,
    )
    assert client._get_ws_endpoint() == "ws://localhost:8000/ws/nodes/?api_key=test-key"


def _run_with_script(client, outcomes, sleeps):
    """Drive ``_run`` with scripted connect outcomes (an Exception to fail, or
    None to connect and reset the backoff), recording each sleep."""
    import asyncio
    from unittest.mock import patch

    outcomes = list(outcomes)

    async def fake_connect():
        outcome = outcomes.pop(0)
        if not outcomes:
            client._running = False
        if outcome is None:
            client._backoff = 1.0  # what a successful connect does
            raise ConnectionError("dropped after connect")
        raise outcome

    async def fake_sleep(delay):
        sleeps.append(delay)

    client._running = True
    with patch.object(client, "_connect_and_receive", fake_connect), patch(
        "src.ws_client.asyncio.sleep", fake_sleep
    ):
        asyncio.run(client._run())


def _client():
    return MeshflowWSClient(
        ws_url="ws://localhost:8000", api_key="k", on_traceroute=lambda _t: None
    )


def test_reconnect_backoff_grows_exponentially_to_cap():
    client = _client()
    sleeps = []
    _run_with_script(client, [OSError("x")] * 10, sleeps)
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]


def test_reconnect_backoff_resets_after_successful_connect():
    client = _client()
    sleeps = []
    _run_with_script(client, [OSError("x")] * 4 + [None] + [OSError("x")] * 2, sleeps)
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 1.0, 2.0, 4.0]
