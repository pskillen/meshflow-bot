"""Tests for throttled self telemetry (TP-1)."""

import time
import unittest
from test.fake_radio import FakeRadio
from unittest.mock import MagicMock, patch

import schedule

from src.bot import MeshflowBot
from src.meshtastic.self_telemetry import (
    SelfTelemetryThrottle,
    interval_from_env,
    telemetry_variant,
)
from src.meshtastic.serializers import MeshtasticPacketSerializer
from src.meshtastic.translation import packet_to_incoming

ME = "!aabbccdd"


def _packet(variant, values, *, sender=ME, rx_time=None):
    packet = {
        "fromId": sender,
        "toId": "!ffffffff",
        "decoded": {
            "portnum": "TELEMETRY_APP",
            "telemetry": {"time": 1, variant: values},
        },
    }
    if rx_time is not None:
        packet["rxTime"] = rx_time
    return packet


class TestTranslation(unittest.TestCase):
    def test_every_variant_from_local_node_is_self_telemetry(self):
        for variant in (
            "deviceMetrics",
            "localStats",
            "powerMetrics",
            "environmentMetrics",
            "airQualityMetrics",
            "someFutureVariant",  # 2.8 may add variants
        ):
            event = packet_to_incoming(_packet(variant, {"x": 1}), local_node_id=ME)
            self.assertTrue(event.is_self_telemetry, variant)
            self.assertEqual(event.self_telemetry_variant, variant)

    def test_other_nodes_telemetry_is_not_self(self):
        event = packet_to_incoming(
            _packet("deviceMetrics", {"batteryLevel": 5}, sender="!11112222"),
            local_node_id=ME,
        )
        self.assertFalse(event.is_self_telemetry)
        self.assertIsNone(event.self_telemetry_variant)

    def test_telemetry_without_variant_has_no_variant(self):
        packet = {
            "fromId": ME,
            "decoded": {"portnum": "TELEMETRY_APP", "telemetry": {"time": 1}},
        }
        event = packet_to_incoming(packet, local_node_id=ME)
        self.assertTrue(event.is_self_telemetry)
        self.assertIsNone(event.self_telemetry_variant)

    def test_telemetry_variant_ignores_scalar_fields(self):
        packet = {"decoded": {"telemetry": {"time": 1, "newScalar": 3, "localStats": {}}}}
        self.assertEqual(telemetry_variant(packet), "localStats")


class TestThrottle(unittest.TestCase):
    def test_latest_sample_wins_per_variant(self):
        throttle = SelfTelemetryThrottle(900)
        for battery in (90, 91, 92):
            throttle.record("deviceMetrics", {"battery": battery})
        throttle.record("localStats", {"tx": 7})
        out = throttle.flush()
        self.assertCountEqual(out, [{"battery": 92}, {"tx": 7}])

    def test_flush_clears_so_nothing_is_resent(self):
        throttle = SelfTelemetryThrottle(900)
        throttle.record("deviceMetrics", {"battery": 90})
        self.assertEqual(len(throttle.flush()), 1)
        self.assertEqual(throttle.flush(), [])

    def test_zero_disables(self):
        throttle = SelfTelemetryThrottle(0)
        throttle.record("deviceMetrics", {"battery": 90})
        self.assertFalse(throttle.enabled)
        self.assertEqual(throttle.flush(), [])

    def test_interval_from_env(self):
        self.assertEqual(interval_from_env(None), 900)
        self.assertEqual(interval_from_env("60"), 60)
        self.assertEqual(interval_from_env("0"), 0)
        self.assertEqual(interval_from_env("junk"), 900)
        self.assertEqual(interval_from_env(""), 900)


class TestBotIntegration(unittest.TestCase):
    def setUp(self):
        schedule.clear()
        self.addCleanup(schedule.clear)
        radio = FakeRadio(local_node_id=ME, local_nodenum=0xAABBCCDD)
        self.bot = MeshflowBot(radio=radio)
        self.bot.node_db = MagicMock()
        self.bot.node_db.get_by_radio_id.return_value = None
        self.api = MagicMock()
        self.bot.storage_apis = [self.api]

    def _feed(self, packet):
        self.bot._on_packet(packet_to_incoming(packet, local_node_id=ME))

    def test_burst_gives_one_upload_with_latest_values(self):
        self.bot.self_telemetry = SelfTelemetryThrottle(900)
        for battery in range(80, 90):
            self._feed(_packet("deviceMetrics", {"batteryLevel": battery}))
        self.api.store_raw_packet.assert_not_called()  # nothing until the job runs

        self.bot.upload_self_telemetry()
        self.api.store_raw_packet.assert_called_once()
        sent = self.api.store_raw_packet.call_args.args[0]
        self.assertEqual(sent["decoded"]["telemetry"]["deviceMetrics"]["batteryLevel"], 89)

        self.bot.upload_self_telemetry()  # nothing new since
        self.api.store_raw_packet.assert_called_once()

    def test_one_upload_per_variant(self):
        self.bot.self_telemetry = SelfTelemetryThrottle(900)
        self._feed(_packet("deviceMetrics", {"batteryLevel": 80}))
        self._feed(_packet("localStats", {"numPacketsTx": 5}))
        self._feed(_packet("someFutureVariant", {"x": 1}))
        self._feed(_packet("deviceMetrics", {"batteryLevel": 79}))
        self.bot.upload_self_telemetry()
        self.assertEqual(self.api.store_raw_packet.call_count, 3)

    def test_disabled_never_uploads_or_schedules(self):
        self.bot.self_telemetry = SelfTelemetryThrottle(0)
        self._feed(_packet("deviceMetrics", {"batteryLevel": 80}))
        self.bot.upload_self_telemetry()
        self.api.store_raw_packet.assert_not_called()

        self.bot.node_info = MagicMock()
        with patch("src.bot.time.sleep", side_effect=KeyboardInterrupt):
            self.bot.start_scheduler()
        self.assertEqual(len(schedule.get_jobs()), 1)  # only the daily reset

    def test_job_scheduled_at_interval_when_enabled(self):
        self.bot.self_telemetry = SelfTelemetryThrottle(120)
        self.bot.node_info = MagicMock()
        with patch("src.bot.time.sleep", side_effect=KeyboardInterrupt):
            self.bot.start_scheduler()
        intervals = [j.interval for j in schedule.get_jobs() if j.unit == "seconds"]
        self.assertEqual(intervals, [120])

    def test_no_throttle_configured_drops_self_telemetry(self):
        self._feed(_packet("deviceMetrics", {"batteryLevel": 80}))
        self.api.store_raw_packet.assert_not_called()

    def test_other_nodes_telemetry_still_uploaded_immediately(self):
        self.bot.self_telemetry = SelfTelemetryThrottle(900)
        self._feed(_packet("deviceMetrics", {"batteryLevel": 80}, sender="!11112222"))
        self.api.store_raw_packet.assert_called_once()

    def test_2_7_and_2_8_shaped_payloads(self):
        self.bot.self_telemetry = SelfTelemetryThrottle(900)
        # 2.7: plain deviceMetrics
        self._feed(_packet("deviceMetrics", {"batteryLevel": 80, "uptimeSeconds": 5}))
        # 2.8: unknown extra fields and variants are tolerated
        p28 = _packet("localStats", {"numPacketsTx": 1, "newIn28": 9})
        p28["decoded"]["telemetry"]["unknownScalar"] = 3
        p28["unknownTopLevel"] = {"a": 1}
        self._feed(p28)
        self.bot.upload_self_telemetry()
        self.assertEqual(self.api.store_raw_packet.call_count, 2)


class TestRxTimeFill(unittest.TestCase):
    def setUp(self):
        self.serializer = MeshtasticPacketSerializer()

    def test_missing_rx_time_filled_from_host_clock(self):
        before = int(time.time())
        out = self.serializer.serialise_raw_packet(_packet("deviceMetrics", {}))
        self.assertGreaterEqual(out["rxTime"], before)
        self.assertLessEqual(out["rxTime"], int(time.time()))

    def test_existing_rx_time_kept(self):
        out = self.serializer.serialise_raw_packet(
            _packet("deviceMetrics", {}, rx_time=1234567890)
        )
        self.assertEqual(out["rxTime"], 1234567890)

    def test_filled_for_non_telemetry_packets_too(self):
        out = self.serializer.serialise_raw_packet(
            {"fromId": "!1", "decoded": {"portnum": "TEXT_MESSAGE_APP"}}
        )
        self.assertIn("rxTime", out)
