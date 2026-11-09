"""v4 feeder-scoped URLs: probe, URL mapping, 404 fallback, per-destination mode."""

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, ReadTimeout

from src.api.StorageAPI import StorageAPIWrapper, parse_feeder_urls_mode
from src.data_classes import MeshNode
from src.meshtastic.identity import read_identity
from src.meshtastic.serializers import MeshtasticPacketSerializer
from test.meshtastic.fake_interface import FakeInterface

IDENTITY = read_identity(FakeInterface(0x11223344))
NODENUM = IDENTITY.node_num
PACKET = {"id": 1, "fromId": "!aabbccdd", "decoded": {"portnum": "TEXT_MESSAGE_APP"}}


def make_wrapper(mode="auto", api_version=3, base="http://api.test", **kwargs):
    return StorageAPIWrapper(
        base,
        token="secret",
        api_version=api_version,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: NODENUM,
        meshtastic_identity_provider=lambda: IDENTITY,
        feeder_urls_mode=mode,
        retry_delays=(),
        **kwargs,
    )


def ok(body=None):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = body or {"ok": True, "internal_id": 7}
    return response


def error(status, code=None):
    response = MagicMock()
    response.status_code = status
    response.text = "x"
    response.json.return_value = {"detail": "d", **({"code": code} if code else {})}
    response.raise_for_status.side_effect = HTTPError(response=response)
    return response


def a_node():
    node = MeshNode()
    node.user = MeshNode.User(node_id="!11112222", long_name="Alice")
    node.position = None
    node.device_metrics = None
    return node


def go_v4(wrapper):
    with patch("requests.get", return_value=ok()):
        wrapper.probe_feeder_urls()
    assert wrapper.uses_v4


def test_parse_mode():
    assert parse_feeder_urls_mode(None) == "auto"
    assert parse_feeder_urls_mode(" ON ") == "on"
    assert parse_feeder_urls_mode("off") == "off"
    assert parse_feeder_urls_mode("bogus") == "auto"


def test_starts_legacy_and_200_switches_to_v4():
    wrapper = make_wrapper()
    assert not wrapper.uses_v4
    assert wrapper._get_url("raw_packet") == f"/api/v3/packets/{NODENUM}/ingest/"
    with patch("requests.get", return_value=ok()) as get:
        wrapper.probe_feeder_urls()
    assert get.call_args.args[0] == "http://api.test/api/v4/feeder/identity/"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Token secret"
    assert wrapper.uses_v4
    assert wrapper._get_url("raw_packet") == "/api/v4/feeder/meshtastic/ingest/"
    assert wrapper._get_url("nodes") == "/api/v4/feeder/meshtastic/nodes/"
    assert wrapper._get_url("bot_version") == "/api/v4/feeder/bot-version/"
    assert wrapper._get_url("node_by_id", {"node_id": 5}) == "/api/nodes/5"


def test_404_stays_legacy():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=error(404)):
        wrapper.probe_feeder_urls()
    assert not wrapper.uses_v4


def test_404_after_v4_goes_back_to_legacy():
    wrapper = make_wrapper()
    go_v4(wrapper)
    with patch("requests.get", return_value=error(404)):
        wrapper.probe_feeder_urls()
    assert not wrapper.uses_v4


def test_shared_api_key_stays_legacy_with_one_error(caplog):
    wrapper = make_wrapper()
    with caplog.at_level(logging.INFO):
        with patch("requests.get", return_value=error(403, "shared_api_key")):
            wrapper.probe_feeder_urls()
    assert not wrapper.uses_v4
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "one API key per feeder" in errors[0].getMessage()


@pytest.mark.parametrize(
    "answer",
    [
        error(403, "feeder_not_linked"),
        error(403),
        error(401),
        error(500),
        ReadTimeout("slow"),
        RequestsConnectionError("down"),
    ],
)
@pytest.mark.parametrize("start_v4", [False, True])
def test_other_answers_keep_current_mode(answer, start_v4, caplog):
    wrapper = make_wrapper()
    if start_v4:
        go_v4(wrapper)
    kwargs = (
        {"side_effect": answer}
        if isinstance(answer, Exception)
        else {"return_value": answer}
    )
    with caplog.at_level(logging.INFO):
        with patch("requests.get", **kwargs):
            wrapper.probe_feeder_urls()
    assert wrapper.uses_v4 is start_v4
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_probe_never_starts_identity_backoff():
    wrapper = make_wrapper()
    for answer in (error(403, "shared_api_key"), error(403, "feeder_not_linked")):
        with patch("requests.get", return_value=answer):
            wrapper.probe_feeder_urls()
    assert not wrapper._identity_backoff_active()
    with patch("requests.post", return_value=ok()):
        assert wrapper.store_raw_packet(PACKET) is not None


def test_mode_change_is_logged_once_and_calls_back(caplog):
    changes = []
    wrapper = make_wrapper(on_feeder_urls_change=changes.append)
    with caplog.at_level(logging.INFO):
        with patch("requests.get", return_value=ok()):
            wrapper.probe_feeder_urls()
            wrapper.probe_feeder_urls()
    assert changes == [True]
    infos = [r for r in caplog.records if "feeder URLs" in r.getMessage()]
    assert len(infos) == 1 and "http://api.test" in infos[0].getMessage()


def test_two_destinations_decide_separately():
    prod = make_wrapper(base="http://prod.test")
    pre = make_wrapper(base="http://pre.test")

    def fake_get(url, **_kw):
        return ok() if url.startswith("http://pre.test") else error(404)

    with patch("requests.get", side_effect=fake_get):
        prod.probe_feeder_urls()
        pre.probe_feeder_urls()
    assert (prod.uses_v4, pre.uses_v4) == (False, True)


def test_off_never_probes():
    wrapper = make_wrapper("off")
    with patch("requests.get") as get:
        wrapper.probe_feeder_urls()
    get.assert_not_called()
    assert not wrapper.uses_v4


def test_on_uses_v4_at_once_and_falls_back_on_404():
    wrapper = make_wrapper("on")
    assert wrapper.uses_v4
    assert wrapper._get_url("raw_packet") == "/api/v4/feeder/meshtastic/ingest/"
    with (
        patch("requests.post", return_value=error(404)),
        patch("requests.get", return_value=error(404)) as get,
    ):
        assert wrapper.store_raw_packet(PACKET) is None
    get.assert_not_called()
    assert not wrapper.uses_v4


def test_api_version_1_never_uses_v4():
    wrapper = make_wrapper("on", api_version=1)
    assert not wrapper.uses_v4
    with patch("requests.get", return_value=ok()) as get:
        wrapper.probe_feeder_urls()
    get.assert_not_called()
    assert wrapper._get_url("raw_packet") == "/api/raw-packet/"


def test_meshcore_wrapper_never_probes():
    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="k",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 0,
        meshcore_feeder_prefix_provider=lambda: "1a37f5aea4a1",
        feeder_urls_mode="on",
    )
    with patch("requests.get", return_value=ok()) as get:
        wrapper.probe_feeder_urls()
    get.assert_not_called()
    assert not wrapper.uses_v4
    assert (
        wrapper._meshcore_feeder_url("packets/ingest/")
        == "/api/meshcore/feeders/1a37f5aea4a1/packets/ingest/"
    )


@pytest.mark.parametrize("op", ["packet", "node", "bot_version"])
def test_v4_upload_404_falls_back(op):
    wrapper = make_wrapper()
    go_v4(wrapper)
    call = {
        "packet": lambda: wrapper.store_raw_packet(PACKET),
        "node": lambda: wrapper.store_node(a_node()),
        "bot_version": lambda: wrapper.report_bot_version(),
    }[op]
    with (
        patch("requests.post", return_value=error(404)),
        patch("requests.put", return_value=error(404)),
        patch("requests.get", return_value=error(404)) as get,
    ):
        call()
    get.assert_not_called()
    assert not wrapper.uses_v4
    wrapper.shutdown()


def test_probe_200_without_identity_json_is_not_v4(caplog):
    wrapper = make_wrapper()
    html = MagicMock()
    html.status_code = 200
    html.json.side_effect = ValueError("not json")
    for response in (html, ok({"detail": "maintenance"})):
        with patch("requests.get", return_value=response):
            wrapper.probe_feeder_urls()
        assert not wrapper.uses_v4
    go_v4(wrapper)
    with patch("requests.get", return_value=html):
        wrapper.probe_feeder_urls()
    assert wrapper.uses_v4


def test_v4_404_resends_packet_on_legacy():
    wrapper = make_wrapper()
    go_v4(wrapper)
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return error(404) if "/api/v4/" in url else ok()

    with patch("requests.post", side_effect=post):
        assert wrapper.store_raw_packet(PACKET) is not None
    assert urls == [
        "http://api.test/api/v4/feeder/meshtastic/ingest/",
        f"http://api.test/api/v3/packets/{NODENUM}/ingest/",
    ]
    assert not wrapper.uses_v4


def test_v4_404_then_probe_200_does_not_flap_until_interval_passes():
    """Mixed replicas: identity answers 200 but ingest 404s. No packet is lost
    and the bot stays on legacy until a probe interval has passed."""
    now = [1000.0]
    wrapper = make_wrapper(clock=lambda: now[0])
    go_v4(wrapper)
    posts = []

    def post(url, **kwargs):
        posts.append(url)
        return error(404) if "/api/v4/" in url else ok()

    with patch("requests.post", side_effect=post), patch(
        "requests.get", return_value=ok()
    ):
        results = []
        for _ in range(5):
            wrapper.probe_feeder_urls()
            results.append(wrapper.store_raw_packet(PACKET))
        assert all(r is not None for r in results)
        assert sum("/api/v4/" in u for u in posts) == 1
        assert not wrapper.uses_v4
        now[0] += 3601
        wrapper.probe_feeder_urls()
        assert wrapper.uses_v4


def test_v4_upload_403_backs_off_as_today():
    wrapper = make_wrapper()
    go_v4(wrapper)
    with patch("requests.post", return_value=error(403, "feeder_not_linked")):
        wrapper.store_raw_packet(PACKET)
    assert wrapper._identity_backoff_active()


def test_v4_bot_version_has_meshtastic_fields():
    wrapper = make_wrapper()
    go_v4(wrapper)
    with patch("requests.put", return_value=ok()) as put:
        assert wrapper.report_bot_version() is True
    assert put.call_args.args[0] == "http://api.test/api/v4/feeder/bot-version/"
    body = put.call_args.kwargs["json"]
    assert body["meshtastic_node_num"] == NODENUM
    assert "bot_version" in body
    wrapper.shutdown()


def test_legacy_bot_version_path_unchanged_when_not_v4():
    wrapper = make_wrapper(api_version=2)
    with patch("requests.put", return_value=ok()) as put:
        wrapper.report_bot_version()
    assert put.call_args.args[0].endswith(f"/api/packets/{NODENUM}/bot-version/")
    wrapper.shutdown()


# --- the first NodeDB upload waits for the v4 probe ---------------------


def test_first_node_upload_probes_first_and_goes_v4():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=ok()) as get, patch(
        "requests.post", return_value=ok()
    ) as post:
        wrapper.store_node(a_node())
    assert get.call_count == 1
    assert post.call_args.args[0] == "http://api.test/api/v4/feeder/meshtastic/nodes/"
    wrapper.shutdown()


def test_first_node_upload_goes_legacy_when_probe_says_404():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=error(404)), patch(
        "requests.post", return_value=ok()
    ) as post:
        wrapper.store_node(a_node())
    assert post.call_args.args[0] == f"http://api.test/api/v3/packets/{NODENUM}/nodes/"
    wrapper.shutdown()


def test_probe_runs_only_once_across_uploads():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=ok()) as get, patch(
        "requests.post", return_value=ok()
    ):
        wrapper.store_node(a_node())
        wrapper.store_node(a_node())
        wrapper.store_raw_packet(PACKET)
    assert get.call_count == 1
    wrapper.shutdown()


@pytest.mark.parametrize("mode", ["on", "off"])
def test_on_and_off_do_not_probe_for_an_upload(mode):
    wrapper = make_wrapper(mode=mode)
    with patch("requests.get") as get, patch("requests.post", return_value=ok()):
        wrapper.store_node(a_node())
    get.assert_not_called()
    wrapper.shutdown()


def test_node_is_held_while_api_unreachable_then_sent_on_v4_after_a_probe():
    now = [1000.0]
    wrapper = make_wrapper(clock=lambda: now[0])
    with patch("requests.get", side_effect=RequestsConnectionError("down")), patch(
        "requests.post"
    ) as post:
        assert wrapper.store_node(a_node()) is None
    post.assert_not_called()
    assert not wrapper.uses_v4
    sent = []
    with patch("requests.get", return_value=ok()), patch(
        "requests.post", side_effect=lambda url, **kw: sent.append(url) or ok()
    ):
        now[0] += 3600
        wrapper.probe_feeder_urls()
        for thread in threading.enumerate():
            if thread.name == "held-node-sync":
                thread.join(5)
    assert sent == ["http://api.test/api/v4/feeder/meshtastic/nodes/"]
    wrapper.shutdown()


def test_unreachable_probe_is_not_repeated_on_every_upload():
    wrapper = make_wrapper()
    with patch("requests.get", side_effect=RequestsConnectionError("down")) as get:
        wrapper.store_node(a_node())
        wrapper.store_node(a_node())
    assert get.call_count == 1
    wrapper.shutdown()


def join_held_sync():
    for thread in threading.enumerate():
        if thread.name == "held-node-sync":
            thread.join(5)


def release_with(wrapper, now, response):
    """Advance past the probe throttle, probe with ``response`` and collect the
    URLs the held nodes were sent to."""
    sent = []
    with patch("requests.get", return_value=response), patch(
        "requests.post", side_effect=lambda url, **kw: sent.append(url) or ok()
    ):
        now[0] += 3600
        wrapper.probe_feeder_urls()
        join_held_sync()
    return sent


V4_NODES = "http://api.test/api/v4/feeder/meshtastic/nodes/"
LEGACY_NODES = f"http://api.test/api/v3/packets/{NODENUM}/nodes/"


@pytest.mark.parametrize("status", [500, 502, 503, 408, 429])
def test_a_probe_answered_5xx_408_or_429_holds_nodes_then_sends_v4(status):
    now = [1000.0]
    wrapper = make_wrapper(clock=lambda: now[0])
    with patch("requests.get", return_value=error(status)), patch(
        "requests.post"
    ) as post:
        assert wrapper.store_node(a_node()) is None
    post.assert_not_called()
    assert not wrapper._probe_decided
    assert release_with(wrapper, now, ok()) == [V4_NODES]
    assert wrapper.uses_v4
    wrapper.shutdown()


@pytest.mark.parametrize("status", [401, 403, 400])
def test_a_probe_answered_other_4xx_is_decided_and_does_not_hold(status):
    wrapper = make_wrapper()
    with patch("requests.get", return_value=error(status)), patch(
        "requests.post", return_value=ok()
    ) as post:
        wrapper.store_node(a_node())
    assert post.call_args.args[0] == LEGACY_NODES
    wrapper.shutdown()


def test_a_probe_answering_200_without_the_identity_does_not_hold_uploads():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=ok({"html": "proxy"})), patch(
        "requests.post", return_value=ok()
    ) as post:
        wrapper.store_node(a_node())
    assert post.call_args.args[0] == LEGACY_NODES
    wrapper.shutdown()


def test_probe_is_not_decided_until_uses_v4_is_set():
    """A concurrent upload must not see "decided" while v4 is still unset."""
    wrapper = make_wrapper()
    in_json, release = threading.Event(), threading.Event()
    response = ok()

    def slow_json():
        in_json.set()
        release.wait(5)
        return {"internal_id": 7}

    response.json.side_effect = slow_json
    results = {}
    with patch("requests.get", return_value=response), patch(
        "requests.post", side_effect=lambda url, **kw: results.setdefault("url", url) and ok()
    ):
        first = threading.Thread(target=wrapper.probe_feeder_urls)
        first.start()
        assert in_json.wait(5)
        second = threading.Thread(target=lambda: wrapper.store_node(a_node()))
        second.start()
        second.join(0.3)
        assert "url" not in results  # still waiting on the probe, not on legacy
        release.set()
        first.join(5)
        second.join(5)
    assert results["url"] == V4_NODES
    wrapper.shutdown()


def test_unreachable_probe_is_throttled_from_the_probe_end():
    now = [1000.0]
    wrapper = make_wrapper(clock=lambda: now[0])

    def slow_failure(*args, **kwargs):
        now[0] += 30  # a read timeout: the probe itself takes the throttle time
        raise ReadTimeout("slow")

    with patch("requests.get", side_effect=slow_failure) as get:
        for _ in range(5):
            wrapper.store_node(a_node())
    assert get.call_count == 1
    wrapper.shutdown()


def test_node_held_after_the_releasing_probe_is_not_stranded():
    wrapper = make_wrapper()
    sent = []
    # The probe decides (nothing held yet) between the caller's check and insert.
    calls = iter([False])

    def ensure():
        if next(calls, True) is False:
            wrapper._probe_decided = True
            return False
        return True

    wrapper._ensure_probed = ensure
    with patch("requests.post", side_effect=lambda url, **kw: sent.append(url) or ok()):
        assert wrapper.store_node(a_node()) is None
        join_held_sync()
    assert sent == [LEGACY_NODES]
    assert not wrapper._held_nodes
    wrapper.shutdown()


def test_first_raw_packet_upload_probes_first():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=ok()) as get, patch(
        "requests.post", return_value=ok()
    ) as post:
        wrapper.store_raw_packet(PACKET)
    assert get.call_count == 1
    assert "/api/v4/feeder/" in post.call_args.args[0]
    wrapper.shutdown()


def test_first_bot_version_report_probes_first():
    wrapper = make_wrapper()
    with patch("requests.get", return_value=ok()) as get, patch(
        "requests.put", return_value=ok()
    ) as put:
        wrapper.report_bot_version()
    assert get.call_count == 1
    assert put.call_args.args[0] == "http://api.test/api/v4/feeder/bot-version/"
    wrapper.shutdown()


def test_concurrent_first_uploads_share_one_probe():
    wrapper = make_wrapper()
    gate = threading.Event()
    gets = []

    def slow_get(*args, **kwargs):
        gets.append(1)
        gate.wait(5)
        return ok()

    urls = []
    with patch("requests.get", side_effect=slow_get), patch(
        "requests.post", side_effect=lambda url, **kw: urls.append(url) or ok()
    ):
        threads = [
            threading.Thread(target=lambda: wrapper.store_node(a_node()))
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        threading.Event().wait(0.3)
        gate.set()
        for thread in threads:
            thread.join(5)
    assert len(gets) == 1
    assert urls == [V4_NODES] * 6
    wrapper.shutdown()


def test_held_node_is_sent_on_legacy_once_when_the_probe_says_404():
    now = [1000.0]
    wrapper = make_wrapper(clock=lambda: now[0])
    with patch("requests.get", side_effect=RequestsConnectionError("down")):
        wrapper.store_node(a_node())
    assert release_with(wrapper, now, error(404)) == [LEGACY_NODES]
    wrapper.shutdown()


def test_a_second_release_sends_nothing():
    now = [1000.0]
    wrapper = make_wrapper(clock=lambda: now[0])
    with patch("requests.get", side_effect=RequestsConnectionError("down")):
        wrapper.store_node(a_node())
    assert release_with(wrapper, now, ok()) == [V4_NODES]
    assert release_with(wrapper, now, ok()) == []
    wrapper.shutdown()


def test_identity_rejection_names_the_local_nodenum_when_identity_is_empty(caplog):
    empty = MagicMock()
    empty.node_num = None
    wrapper = make_wrapper(api_version=2, mode="off")
    wrapper._meshtastic_identity_provider = lambda: empty
    with patch("requests.post", return_value=error(403)), caplog.at_level(
        logging.ERROR
    ):
        wrapper.store_node(a_node())
    assert f"reporting node number {NODENUM}" in caplog.text
    wrapper.shutdown()
