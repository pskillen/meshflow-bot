"""Background retry of the bot-version report and per-node (NodeDB sync) uploads."""

import threading
from unittest.mock import MagicMock, patch

from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError

from src.api.StorageAPI import StorageAPIWrapper
from src.data_classes import MeshNode
from src.meshtastic.serializers import MeshtasticPacketSerializer


class FakeScheduler:
    """Records scheduled retries instead of starting timers."""

    def __init__(self):
        self.calls = []

    def __call__(self, delay, fn):
        handle = MagicMock()
        self.calls.append((delay, fn, handle))
        return handle

    def run_last(self):
        self.calls[-1][1]()


def make_wrapper(scheduler):
    return StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 42424242,
        retry_delays=(15.0, 45.0),
        retry_scheduler=scheduler,
    )


def http_error(status):
    response = MagicMock()
    response.status_code = status
    response.text = "x"
    return HTTPError(response=response)


def a_node():
    node = MeshNode()
    node.user = MeshNode.User(node_id="!11112222", long_name="Alice")
    node.position = None
    node.device_metrics = None
    return node


def test_bot_version_retries_connection_error_then_succeeds():
    sched = FakeScheduler()
    wrapper = make_wrapper(sched)
    with patch.object(
        wrapper, "_put", side_effect=[RequestsConnectionError("down"), MagicMock()]
    ) as put:
        assert wrapper.report_bot_version() is False
        assert [c[0] for c in sched.calls] == [15.0]
        sched.run_last()
    assert put.call_count == 2
    assert len(sched.calls) == 1  # success: nothing further scheduled


def test_bot_version_retry_capped_at_three_attempts():
    sched = FakeScheduler()
    wrapper = make_wrapper(sched)
    with patch.object(wrapper, "_put", side_effect=http_error(503)) as put:
        wrapper.report_bot_version()
        sched.run_last()
        sched.run_last()
    assert put.call_count == 3
    assert [c[0] for c in sched.calls] == [15.0, 45.0]


def test_bot_version_does_not_retry_403_409_or_4xx():
    for status in (403, 409, 400, 404):
        sched = FakeScheduler()
        wrapper = make_wrapper(sched)
        with patch.object(wrapper, "_put", side_effect=http_error(status)):
            wrapper.report_bot_version()
        assert sched.calls == [], status


def test_bot_version_retry_does_not_block_caller():
    sched = FakeScheduler()
    wrapper = make_wrapper(sched)
    with patch.object(wrapper, "_put", side_effect=http_error(500)) as put:
        wrapper.report_bot_version()
    assert put.call_count == 1  # retries only run when the scheduler fires


def test_store_node_retries_transient_failure():
    sched = FakeScheduler()
    wrapper = make_wrapper(sched)
    ok = MagicMock()
    ok.json.return_value = {"ok": True}
    with patch.object(wrapper, "_post", side_effect=[http_error(502), ok]) as post:
        assert wrapper.store_node(a_node()) is None
        assert [c[0] for c in sched.calls] == [15.0]
        sched.run_last()
    assert post.call_count == 2
    assert len(sched.calls) == 1


def test_store_node_does_not_retry_identity_rejection_or_4xx():
    for status in (403, 409, 400):
        sched = FakeScheduler()
        wrapper = make_wrapper(sched)
        with patch.object(wrapper, "_post", side_effect=http_error(status)):
            wrapper.store_node(a_node())
        assert sched.calls == [], status


def test_store_node_retry_replaces_pending_retry_for_same_node():
    sched = FakeScheduler()
    wrapper = make_wrapper(sched)
    with patch.object(wrapper, "_post", side_effect=RequestsConnectionError("x")):
        wrapper.store_node(a_node())
        wrapper.store_node(a_node())
    assert len(sched.calls) == 2
    sched.calls[0][2].cancel.assert_called_once()


def test_real_timer_scheduler_runs_off_thread():
    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 1,
        retry_delays=(0.01,),
    )
    done = threading.Event()
    calls = []

    def put(*args, **kwargs):
        calls.append(threading.current_thread())
        if len(calls) == 1:
            raise RequestsConnectionError("down")
        done.set()
        return MagicMock()

    with patch.object(wrapper, "_put", side_effect=put):
        wrapper.report_bot_version()
        assert done.wait(2)
    assert calls[1] is not threading.main_thread()
