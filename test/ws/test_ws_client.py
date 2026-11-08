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


def test_ws_endpoint_feeder_scoped_when_primary_is_v4():
    state = {"v4": True}
    client = MeshflowWSClient(
        ws_url="ws://localhost:8000",
        api_key="test-key",
        on_traceroute=lambda _target: None,
        feeder_node_id_provider=lambda: 1127973616,
        feeder_scoped_provider=lambda: state["v4"],
    )
    assert (
        client._get_ws_endpoint()
        == "ws://localhost:8000/ws/nodes/?api_key=test-key&feeder_scoped=1"
    )
    state["v4"] = False
    assert (
        client._get_ws_endpoint()
        == "ws://localhost:8000/ws/nodes/?api_key=test-key&feeder_node_id=1127973616"
    )


def test_primary_mode_change_reconnects_the_ws_client():
    from unittest.mock import MagicMock, patch

    from src.api.StorageAPI import StorageAPIWrapper
    from src.meshtastic.serializers import MeshtasticPacketSerializer

    ws = MagicMock()
    api = StorageAPIWrapper(
        "http://api.test",
        token="k",
        api_version=3,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 1,
        on_feeder_urls_change=lambda _v4: ws.reconnect(),
    )
    with patch(
        "requests.get",
        return_value=MagicMock(**{"json.return_value": {"internal_id": 1}}),
    ):
        api.probe_feeder_urls()
        api.probe_feeder_urls()  # unchanged: no second reconnect
    ws.reconnect.assert_called_once()
    assert api.uses_v4


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
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 1.0, 2.0]


# --- real _connect_and_receive against a stub websockets.connect -----------


class _StubConnection:
    """Async context manager standing in for ``websockets.connect(...)``."""

    def __init__(self, messages, then=None):
        self._messages = list(messages)
        self._then = then

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        from websockets.exceptions import ConnectionClosed

        raise ConnectionClosed(None, None)


def _drive_connect(client, conn):
    import asyncio
    from unittest.mock import patch

    client._running = True
    with patch("websockets.connect", return_value=conn):
        try:
            asyncio.run(client._connect_and_receive())
        except Exception:
            pass  # ConnectionClosed propagates to _run, which reconnects


def test_backoff_resets_after_first_message_on_real_connect():
    client = _client()
    client._backoff = 16.0
    _drive_connect(client, _StubConnection(['{"type": "noop"}']))
    assert client._backoff == 1.0


def test_backoff_not_reset_when_server_accepts_then_drops_immediately():
    client = _client()
    client._backoff = 16.0
    _drive_connect(client, _StubConnection([]))
    assert client._backoff == 16.0


def test_backoff_resets_when_connection_was_stable_before_closing():
    from types import SimpleNamespace
    from unittest.mock import patch

    client = _client()
    client._backoff = 16.0
    ticks = iter([100.0, 100.0 + 31.0, 100.0 + 31.0])
    fake_time = SimpleNamespace(monotonic=lambda: next(ticks))
    with patch("src.ws_client.time", fake_time):
        _drive_connect(client, _StubConnection([]))
    assert client._backoff == 1.0
