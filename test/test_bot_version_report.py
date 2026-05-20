"""Tests for bot version reporting to meshflow-api."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api.StorageAPI import StorageAPIWrapper
from src.meshtastic.serializers import MeshtasticPacketSerializer
from src.version import get_bot_version


def test_get_bot_version_from_app_version(monkeypatch) -> None:
    monkeypatch.setenv("APP_VERSION", "  v1.2.3  ")
    assert get_bot_version() == "v1.2.3"


def test_get_bot_version_defaults_to_development(monkeypatch) -> None:
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert get_bot_version() == "development"


def test_report_bot_version_puts_v2_path() -> None:
    wrapper = StorageAPIWrapper(
        "http://api.test",
        token="secret",
        api_version=2,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 42424242,
    )
    mock_response = MagicMock()
    with patch.object(wrapper, "_put", return_value=mock_response) as put:
        assert wrapper.report_bot_version() is True
    put.assert_called_once()
    assert put.call_args[0][0] == "/api/packets/42424242/bot-version/"
    assert put.call_args[1]["json"]["bot_version"] == get_bot_version()


def test_report_bot_version_skipped_for_v1() -> None:
    wrapper = StorageAPIWrapper(
        "http://api.test",
        api_version=1,
        serializer=MeshtasticPacketSerializer(),
        local_meshtastic_nodenum_provider=lambda: 1,
    )
    with patch.object(wrapper, "_put") as put:
        assert wrapper.report_bot_version() is False
    put.assert_not_called()
