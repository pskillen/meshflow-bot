"""Identity headers, bot-version payload and 403/409 backoff in StorageAPIWrapper."""

from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError

from src.api.StorageAPI import StorageAPIWrapper
from src.bot import MeshflowBot
from src.meshtastic.identity import (
    FIRMWARE_HEADER,
    NODE_NUM_HEADER,
    PUBKEY_HEADER,
    read_identity,
)
from src.meshtastic.serializers import MeshtasticPacketSerializer
from src.radio.events import IdentityChanged
from test.fake_radio import FakeRadio
from test.meshtastic.fake_interface import PUBKEY_B64, FakeInterface


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_wrapper(identity=None, clock=None, api_version=2) -> StorageAPIWrapper:
    identity = identity or read_identity(FakeInterface(0x11223344))
    return StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=api_version,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: identity.node_num,
        meshtastic_identity_provider=lambda: identity,
        **({"clock": clock} if clock else {}),
    )


def ok_response():
    response = MagicMock()
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    return response


def error_response(status: int):
    response = MagicMock()
    response.status_code = status
    response.text = '{"detail": "nope"}'
    response.raise_for_status.side_effect = HTTPError(response=response)
    return response


PACKET = {"id": 1, "fromId": "!aabbccdd", "decoded": {"portnum": "TEXT_MESSAGE_APP"}}


def test_identity_headers_on_post_get_and_put():
    wrapper = make_wrapper()
    for method in ("post", "get", "put"):
        with patch(f"requests.{method}", return_value=ok_response()) as call:
            if method == "post":
                wrapper._post("/x", json={})
            elif method == "put":
                wrapper._put("/x", json={})
            else:
                wrapper._get("/x")
        headers = call.call_args.kwargs["headers"]
        assert headers[PUBKEY_HEADER] == PUBKEY_B64
        assert headers[NODE_NUM_HEADER] == str(0x11223344)
        assert headers[FIRMWARE_HEADER] == "2.7.11.abcdef0"
        assert headers["Authorization"] == "Token secret"


def test_absent_identity_fields_send_no_header():
    iface = FakeInterface(pubkey_b64=None, firmware=None)
    wrapper = make_wrapper(read_identity(iface))
    headers = wrapper._get_headers()
    assert PUBKEY_HEADER not in headers
    assert FIRMWARE_HEADER not in headers
    assert headers[NODE_NUM_HEADER] == str(0x11223344)


def test_no_identity_provider_means_no_meshtastic_headers():
    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 1,
    )
    headers = wrapper._get_headers()
    assert not any(k.startswith("X-Meshtastic-") for k in headers)


def test_identity_provider_failure_does_not_break_requests():
    wrapper = make_wrapper()
    wrapper._meshtastic_identity_provider = MagicMock(side_effect=RuntimeError("x"))
    assert "Authorization" in wrapper._get_headers()


def test_bot_version_payload_includes_identity_fields():
    wrapper = make_wrapper()
    with patch.object(wrapper, "_put", return_value=MagicMock()) as put:
        assert wrapper.report_bot_version() is True
    body = put.call_args.kwargs["json"]
    assert body["bot_version"]
    assert body["meshtastic_public_key"] == PUBKEY_B64
    assert body["meshtastic_node_num"] == 0x11223344
    assert body["meshtastic_firmware_version"] == "2.7.11.abcdef0"
    assert body["meshtastic_macaddr"] == "a1:b2:c3:d4:e5:f6"
    assert body["meshtastic_region"] == "EU_868"
    assert body["meshtastic_modem_preset"] == "LONG_FAST"


def test_bot_version_payload_omits_missing_fields():
    iface = FakeInterface(
        pubkey_b64=None, macaddr_b64=None, firmware=None, lora_config_received=False
    )
    wrapper = make_wrapper(read_identity(iface))
    with patch.object(wrapper, "_put", return_value=MagicMock()) as put:
        wrapper.report_bot_version()
    assert set(put.call_args.kwargs["json"]) == {"bot_version", "meshtastic_node_num"}


def test_bot_version_unchanged_without_identity_provider():
    wrapper = StorageAPIWrapper(
        "http://api.test",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 7,
    )
    with patch.object(wrapper, "_put", return_value=MagicMock()) as put:
        wrapper.report_bot_version()
    assert set(put.call_args.kwargs["json"]) == {"bot_version"}


def test_meshcore_bot_version_ignores_meshtastic_identity():
    wrapper = StorageAPIWrapper(
        "http://api.test",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: None,
        meshcore_feeder_prefix_provider=lambda: "abcdef123456",
    )
    with patch.object(wrapper, "_put", return_value=MagicMock()) as put:
        wrapper.report_bot_version()
    assert put.call_args[0][0] == "/api/meshcore/feeders/abcdef123456/bot-version/"
    assert set(put.call_args.kwargs["json"]) == {"bot_version"}


@pytest.mark.parametrize("status", [403, 409])
def test_rejection_logs_error_with_node_number_and_backs_off(status, caplog):
    clock = Clock()
    wrapper = make_wrapper(clock=clock)
    with patch("requests.post", return_value=error_response(status)) as post:
        with caplog.at_level("ERROR"):
            assert wrapper.store_raw_packet(PACKET) is None
        assert post.call_count == 1

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any(
            str(0x11223344) in m and "2.8" in m and str(status) in m for m in errors
        )

        # Within the backoff window: no HTTP request at all.
        clock.now += 10
        assert wrapper.store_raw_packet(PACKET) is None
        assert wrapper.store_node(MagicMock()) is None
        assert post.call_count == 1

        # After it elapses we try again, and the window doubles on a repeat.
        clock.now += 30
        assert wrapper.store_raw_packet(PACKET) is None
        assert post.call_count == 2
        assert wrapper._identity_backoff_seconds == 60.0


def test_backoff_is_capped_and_resets_on_success():
    clock = Clock()
    wrapper = make_wrapper(clock=clock)
    with patch("requests.post", return_value=error_response(403)):
        for _ in range(12):
            clock.now += 10_000
            wrapper.store_raw_packet(PACKET)
    assert wrapper._identity_backoff_seconds == 900.0

    clock.now += 10_000
    with patch("requests.post", return_value=ok_response()):
        assert wrapper.store_raw_packet(PACKET) == {"ok": True}
    assert wrapper._identity_backoff_seconds == 0.0
    assert not wrapper._identity_backoff_active()


def test_other_http_errors_do_not_back_off():
    wrapper = make_wrapper(clock=Clock())
    with patch("requests.post", return_value=error_response(500)) as post:
        wrapper.store_raw_packet(PACKET)
        wrapper.store_raw_packet(PACKET)
    assert post.call_count == 2
    assert not wrapper._identity_backoff_active()


def test_rejection_on_bot_version_logs_but_does_not_block_uploads(caplog):
    wrapper = make_wrapper(clock=Clock())
    with patch("requests.put", return_value=error_response(403)):
        with caplog.at_level("ERROR"):
            assert wrapper.report_bot_version() is False
    assert any(str(0x11223344) in r.getMessage() for r in caplog.records)
    # report_bot_version rejection also starts the backoff for uploads
    assert wrapper._identity_backoff_active()


def test_meshcore_wrapper_never_backs_off():
    wrapper = StorageAPIWrapper(
        "http://api.test",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: None,
        meshcore_feeder_prefix_provider=lambda: "abcdef123456",
    )
    exc = HTTPError(response=error_response(403))
    assert wrapper._handle_identity_rejection(exc, "x") is False


def test_bot_identity_change_rereports_and_reconnects_ws_only_on_number_change():
    bot = MeshflowBot(radio=FakeRadio())
    api = MagicMock()
    ws = MagicMock()
    bot.storage_apis = [api]
    bot.ws_client = ws

    bot._on_identity_changed(IdentityChanged(1, 1))
    api.report_bot_version.assert_called_once()
    ws.reconnect.assert_not_called()

    bot._on_identity_changed(IdentityChanged(1, 2))
    assert api.report_bot_version.call_count == 2
    ws.reconnect.assert_called_once()
