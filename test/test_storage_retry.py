"""Background retry of the bot-version report and per-node (NodeDB sync)
uploads: one worker thread, serial sends, newest call wins."""

import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, ReadTimeout
from requests.exceptions import InvalidURL, SSLError

from src.api.StorageAPI import StorageAPIWrapper
from src.data_classes import MeshNode
from src.meshtastic.serializers import MeshtasticPacketSerializer


def make_wrapper(delays=(0.02, 0.02), gap=0.0):
    return StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 42424242,
        retry_delays=delays,
        retry_gap=gap,
    )


@pytest.fixture
def wrapper():
    w = make_wrapper()
    yield w
    w.shutdown()


def http_error(status):
    response = MagicMock()
    response.status_code = status
    response.text = "x"
    return HTTPError(response=response)


def a_node(name="Alice", node_id="!11112222"):
    node = MeshNode()
    node.user = MeshNode.User(node_id=node_id, long_name=name)
    node.position = None
    node.device_metrics = None
    return node


def ok_response():
    ok = MagicMock()
    ok.json.return_value = {"ok": True}
    return ok


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def settle(w, extra=0.15):
    """Wait for all pending retries to run, then a little longer."""
    assert wait_for(lambda: w._retry_worker.pending() == 0)
    time.sleep(extra)


# --- bot version -----------------------------------------------------------


def test_bot_version_retries_connection_error_then_succeeds(wrapper):
    with patch.object(
        wrapper, "_put", side_effect=[RequestsConnectionError("down"), MagicMock()]
    ) as put:
        assert wrapper.report_bot_version() is False
        assert wait_for(lambda: put.call_count == 2)
        settle(wrapper)
    assert put.call_count == 2  # success: nothing further scheduled


def test_bot_version_retry_capped_at_three_attempts(wrapper):
    with patch.object(wrapper, "_put", side_effect=http_error(503)) as put:
        wrapper.report_bot_version()
        assert wait_for(lambda: put.call_count == 3)
        settle(wrapper)
    assert put.call_count == 3


def test_bot_version_does_not_retry_403_409_or_4xx(wrapper):
    for status in (403, 409, 400, 404):
        with patch.object(wrapper, "_put", side_effect=http_error(status)) as put:
            wrapper.report_bot_version()
            time.sleep(0.06)
        assert put.call_count == 1, status


def test_bot_version_retry_does_not_block_caller():
    w = make_wrapper(delays=(30.0, 30.0))
    try:
        with patch.object(w, "_put", side_effect=http_error(500)) as put:
            w.report_bot_version()
        assert put.call_count == 1  # the retry is 30s away
        assert w._retry_worker.pending() == 1
    finally:
        w.shutdown()


def test_bot_version_retry_dropped_while_identity_backoff_active(wrapper):
    with patch.object(wrapper, "_put", side_effect=http_error(503)) as put:
        wrapper.report_bot_version()
        wrapper._identity_blocked_until = time.monotonic() + 100
        settle(wrapper, 0.1)
    assert put.call_count == 1


def test_newer_bot_version_report_drops_pending_retry():
    w = make_wrapper(delays=(0.2, 0.2))
    try:
        with patch.object(w, "_put", side_effect=[http_error(503), MagicMock()]) as put:
            w.report_bot_version()
            assert w.report_bot_version() is True
            settle(w, 0.4)
        assert put.call_count == 2  # no redundant third PUT
    finally:
        w.shutdown()


# --- nodes -----------------------------------------------------------------


def test_store_node_retries_transient_failure(wrapper):
    with patch.object(
        wrapper, "_post", side_effect=[http_error(502), ok_response()]
    ) as post:
        assert wrapper.store_node(a_node()) is None
        assert wait_for(lambda: post.call_count == 2)
        settle(wrapper)
    assert post.call_count == 2


def test_store_node_does_not_retry_identity_rejection_or_4xx(wrapper):
    for status in (403, 409, 400):
        with patch.object(wrapper, "_post", side_effect=http_error(status)) as post:
            wrapper.store_node(a_node())
            time.sleep(0.06)
        assert post.call_count == 1, status


def test_store_node_retry_is_dropped_while_identity_backoff_active(wrapper):
    with patch.object(wrapper, "_post", side_effect=http_error(503)) as post:
        wrapper.store_node(a_node())
        wrapper._identity_blocked_until = time.monotonic() + 100
        settle(wrapper, 0.1)
    assert post.call_count == 1


def _sent_names(post):
    return [c.kwargs["json"]["user"]["long_name"] for c in post.call_args_list]


def test_newer_successful_store_node_is_not_overwritten_by_stale_retry():
    """OLD fails -> retry pending; NEW succeeds; OLD must never be re-sent."""
    w = make_wrapper(delays=(0.15, 0.15))
    try:
        with patch.object(
            w, "_post", side_effect=[http_error(503), ok_response()]
        ) as post:
            w.store_node(a_node("OLD"))
            w.store_node(a_node("NEW"))
            settle(w, 0.4)
        assert _sent_names(post) == ["OLD", "NEW"]
    finally:
        w.shutdown()


def test_newer_failing_store_node_replaces_pending_retry_payload():
    w = make_wrapper(delays=(0.1, 0.1))
    try:
        with patch.object(w, "_post", side_effect=RequestsConnectionError("x")) as post:
            w.store_node(a_node("OLD"))
            w.store_node(a_node("NEW"))
            assert w._retry_worker.pending() == 1
            settle(w, 0.4)
        # OLD, NEW, then only NEW's two retries: OLD is never re-sent.
        assert _sent_names(post) == ["OLD", "NEW", "NEW", "NEW"]
    finally:
        w.shutdown()


def test_newer_store_node_skipped_by_backoff_still_drops_pending_retry():
    w = make_wrapper(delays=(0.1, 0.1))
    try:
        with patch.object(w, "_post", side_effect=RequestsConnectionError("x")) as post:
            w.store_node(a_node("OLD"))
            w._identity_blocked_until = time.monotonic() + 100
            assert w.store_node(a_node("NEW")) is None  # skipped by back-off
            assert w._retry_worker.pending() == 0
            settle(w, 0.3)
        assert _sent_names(post) == ["OLD"]
    finally:
        w.shutdown()


def test_store_node_bad_json_body_is_not_retried(wrapper):
    bad = MagicMock()
    bad.json.side_effect = ValueError("not json")
    with patch.object(wrapper, "_post", return_value=bad) as post:
        assert wrapper.store_node(a_node()) is None
        time.sleep(0.08)
    assert post.call_count == 1


@pytest.mark.parametrize("exc", [SSLError("tls"), InvalidURL("bad url")])
def test_store_node_does_not_retry_non_transient_request_errors(wrapper, exc):
    with patch.object(wrapper, "_post", side_effect=exc) as post:
        wrapper.store_node(a_node())
        time.sleep(0.08)
    assert post.call_count == 1


def test_store_node_retries_read_timeout(wrapper):
    with patch.object(
        wrapper, "_post", side_effect=[ReadTimeout("slow"), ok_response()]
    ) as post:
        wrapper.store_node(a_node())
        assert wait_for(lambda: post.call_count == 2)


# --- the worker under a long outage ----------------------------------------


def test_200_node_outage_uses_one_extra_thread_and_sends_serially():
    w = make_wrapper(delays=(0.05, 0.05), gap=0.002)
    lock = threading.Lock()
    state = {"in_flight": 0, "max_in_flight": 0, "retry_threads": set()}
    main = threading.current_thread()

    def failing_post(url, json):
        # The first attempts come from the caller's thread and may overlap
        # the worker's; what must be serial is the worker's own retries.
        is_retry = threading.current_thread() is not main
        if is_retry:
            with lock:
                state["in_flight"] += 1
                state["max_in_flight"] = max(
                    state["max_in_flight"], state["in_flight"]
                )
                state["retry_threads"].add(threading.current_thread().ident)
        time.sleep(0.0005)
        if is_retry:
            with lock:
                state["in_flight"] -= 1
        raise RequestsConnectionError("down")

    before = threading.active_count()
    peak = before
    try:
        with patch.object(w, "_post", side_effect=failing_post) as post:
            for i in range(200):
                w.store_node(a_node(f"n{i}", node_id=f"!{i:08x}"))
            end = time.monotonic() + 20
            while post.call_count < 600 and time.monotonic() < end:
                peak = max(peak, threading.active_count())
                time.sleep(0.005)
        assert post.call_count == 600  # 200 nodes x 3 attempts, then give up
        assert peak - before <= 1
        assert len(state["retry_threads"]) == 1
        assert state["max_in_flight"] == 1
    finally:
        w.shutdown()


def test_shutdown_stops_thread_without_blocking():
    w = make_wrapper(delays=(30.0, 30.0))
    with patch.object(w, "_post", side_effect=http_error(503)):
        w.store_node(a_node())
    thread = w._retry_worker._thread
    assert thread is not None and thread.is_alive()
    started = time.monotonic()
    w.shutdown()
    assert time.monotonic() - started < 0.5
    thread.join(2)
    assert not thread.is_alive()
    assert w._retry_worker.pending() == 0


# --- logging ---------------------------------------------------------------


def test_first_failure_is_error_retries_warning_one_give_up_line(wrapper, caplog):
    caplog.set_level(logging.INFO, logger="src.api.StorageAPI")
    with patch.object(wrapper, "_post", side_effect=RequestsConnectionError("x")):
        wrapper.store_node(a_node())
        settle(wrapper)
    failures = [r for r in caplog.records if "Network error storing node" in r.message]
    assert [r.levelno for r in failures] == [
        logging.ERROR,
        logging.WARNING,
        logging.WARNING,
    ]
    giveups = [r for r in caplog.records if "Giving up" in r.message]
    assert len(giveups) == 1


# --- request timeout -------------------------------------------------------


def test_requests_carry_a_connect_and_read_timeout():
    w = make_wrapper()
    resp = MagicMock()
    with patch("src.api.BaseAPIWrapper.requests") as req:
        req.get.return_value = req.post.return_value = req.put.return_value = resp
        w._get("/a")
        w._post("/a", json={})
        w._put("/a", json={})
    for fn in (req.get, req.post, req.put):
        assert fn.call_args.kwargs["timeout"] == (5, 30)


def test_black_holed_api_times_out_and_is_retried(wrapper):
    with patch(
        "src.api.BaseAPIWrapper.requests.post",
        side_effect=[ReadTimeout("no answer"), ok_response()],
    ) as post:
        wrapper.store_node(a_node())
        assert wait_for(lambda: post.call_count == 2)
