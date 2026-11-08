"""v4 feeder-scoped URLs: probe, URL mapping, 404 fallback, per-destination mode."""

import logging
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
    response.json.return_value = body or {"ok": True}
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
        assert wrapper.store_raw_packet(PACKET) == {"ok": True}


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


def test_on_uses_v4_at_once_and_reprobes_on_404():
    wrapper = make_wrapper("on")
    assert wrapper.uses_v4
    assert wrapper._get_url("raw_packet") == "/api/v4/feeder/meshtastic/ingest/"
    with (
        patch("requests.post", return_value=error(404)),
        patch("requests.get", return_value=error(404)) as get,
    ):
        assert wrapper.store_raw_packet(PACKET) is None
    get.assert_called_once()
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
def test_v4_upload_404_falls_back_and_probes_again(op):
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
    get.assert_called_once()
    assert not wrapper.uses_v4
    wrapper.shutdown()


def test_v4_upload_404_then_probe_200_stays_v4():
    wrapper = make_wrapper()
    go_v4(wrapper)
    with patch("requests.get", return_value=ok()):
        with patch("requests.post", return_value=error(404)):
            wrapper.store_raw_packet(PACKET)
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
