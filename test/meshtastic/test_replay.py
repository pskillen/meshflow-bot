"""Detection and handling of the Meshtastic 2.8 connect-time NodeDB replay."""

import json
import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.bot import MeshflowBot
from src.meshtastic.replay import (
    REPLAY_COUNTER_NAME,
    ReplaySummary,
    is_replayed,
    parse_mode,
)
from src.meshtastic.translation import packet_to_incoming
from src.persistence import packet_dump
from src.radio.errors import ErrorCounter
from test.fake_radio import FakeRadio

FIXTURE = Path(__file__).parent / "fixtures" / "replay_capture.jsonl"
# Feeder that took the captures (!e0a76739).
SELF_NUM = 3769067321


def _load(which):
    with open(FIXTURE) as f:
        rows = [json.loads(line) for line in f]
    return [r["packet"] for r in rows if r["set"] == which]


class TestClassifier(unittest.TestCase):
    def test_burst_records_are_replayed_and_self_is_not(self):
        packets = _load("hop4")
        self.assertEqual(len(packets), 89)
        self_packets = [p for p in packets if p["from"] == SELF_NUM]
        others = [p for p in packets if p["from"] != SELF_NUM]
        self.assertTrue(self_packets)
        for p in self_packets:
            self.assertFalse(is_replayed(p, SELF_NUM), p)
        # Every non-self record without an RSSI is a replay; the few with one
        # are live receptions that arrived mixed into the burst.
        replayed = [p for p in others if is_replayed(p, SELF_NUM)]
        self.assertEqual(len(replayed), len([p for p in others if "rxRssi" not in p]))
        self.assertGreaterEqual(len(replayed), 70)
        for p in replayed:
            self.assertNotIn("rxRssi", p)
            self.assertEqual(p.get("priority"), "BACKGROUND")

    def test_live_records_are_not_replayed(self):
        live = _load("live")
        self.assertEqual(len(live), 20)
        for p in live:
            self.assertIn("rxRssi", p)
            self.assertFalse(is_replayed(p, SELF_NUM), p)

    def test_unknown_local_nodenum_never_classifies(self):
        p = {"from": 1, "id": 2}
        self.assertFalse(is_replayed(p, None))

    def test_flag_travels_on_the_event(self):
        replay = {"from": 1, "decoded": {"portnum": "POSITION_APP"}}
        event = packet_to_incoming(
            replay, local_node_id="!e0a76739", local_nodenum=SELF_NUM
        )
        self.assertTrue(event.replayed)
        live = {**replay, "rxRssi": -80}
        event = packet_to_incoming(
            live, local_node_id="!e0a76739", local_nodenum=SELF_NUM
        )
        self.assertFalse(event.replayed)


class TestParseMode(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(parse_mode(None), "drop")
        self.assertEqual(parse_mode(""), "drop")
        self.assertEqual(parse_mode(" Flag "), "flag")
        self.assertEqual(parse_mode("pass"), "pass")
        self.assertEqual(parse_mode("bogus"), "drop")


class TestSummary(unittest.TestCase):
    def test_one_info_line_per_connect_and_counter(self):
        now = [100.0]
        counter = ErrorCounter()
        summary = ReplaySummary(
            "drop", counter=counter, clock=lambda: now[0], use_timer=False
        )
        summary.start_connect()
        for _ in range(3):
            now[0] += 10
            summary.record()
        with self.assertLogs("src.meshtastic.replay", level=logging.INFO) as logs:
            line = summary.flush()
        self.assertEqual(line, "replayed packets: 3 dropped in the first 30 s")
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(counter.get(REPLAY_COUNTER_NAME), 3)
        self.assertIsNone(summary.flush())

    def test_flag_mode_wording_and_next_connect_flushes(self):
        summary = ReplaySummary("flag", clock=lambda: 5.0, use_timer=False)
        summary.start_connect()
        summary.record()
        with self.assertLogs("src.meshtastic.replay", level=logging.INFO) as logs:
            summary.start_connect()
        self.assertIn("1 flagged in the first 0 s", logs.output[0])


class TestBotModes(unittest.TestCase):
    def _bot(self, mode):
        bot = MeshflowBot(radio=FakeRadio(local_node_id="!e0a76739", local_nodenum=SELF_NUM))
        bot.replayed_packets_mode = mode
        api = MagicMock()
        bot.storage_apis = [api]
        bot.node_db = MagicMock()
        bot.node_info = MagicMock()
        return bot, api

    def _replay_event(self):
        packet = {
            "from": 7,
            "fromId": "!00000007",
            "toId": "^all",
            "priority": "BACKGROUND",
            "decoded": {"portnum": "TELEMETRY_APP", "telemetry": {}},
        }
        return packet_to_incoming(
            packet, local_node_id="!e0a76739", local_nodenum=SELF_NUM
        )

    def test_drop_does_not_upload_or_count_activity(self):
        bot, api = self._bot("drop")
        with patch("src.bot.dump_packet"):
            bot._on_packet(self._replay_event())
        api.store_raw_packet.assert_not_called()
        bot.node_info.node_packet_received.assert_not_called()

    def test_flag_uploads_with_replayed_key(self):
        bot, api = self._bot("flag")
        event = self._replay_event()
        with patch("src.bot.dump_packet"):
            bot._on_packet(event)
        api.store_raw_packet.assert_called_once()
        body = api.store_raw_packet.call_args.args[0]
        self.assertIs(body["replayed"], True)
        self.assertNotIn("replayed", event.raw)  # the library dict is untouched

    def test_pass_is_todays_behaviour(self):
        bot, api = self._bot("pass")
        with patch("src.bot.dump_packet") as dump:
            bot._on_packet(self._replay_event())
        body = api.store_raw_packet.call_args.args[0]
        self.assertNotIn("replayed", body)
        self.assertFalse(dump.call_args.kwargs["replayed"])

    def test_live_packet_uploads_unflagged_in_every_mode(self):
        for mode in ("drop", "flag", "pass"):
            bot, api = self._bot(mode)
            packet = {
                "from": 7,
                "fromId": "!00000007",
                "rxRssi": -80,
                "decoded": {"portnum": "TELEMETRY_APP", "telemetry": {}},
            }
            event = packet_to_incoming(
                packet, local_node_id="!e0a76739", local_nodenum=SELF_NUM
            )
            with patch("src.bot.dump_packet"):
                bot._on_packet(event)
            self.assertNotIn("replayed", api.store_raw_packet.call_args.args[0])


class TestReplayDump(unittest.TestCase):
    def test_replayed_go_to_replay_folder(self):
        import tempfile

        packet = {"from": 7, "decoded": {"portnum": "POSITION_APP"}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            packet_dump, "dump_portnums", ["*"]
        ):
            packet_dump.dump_packet(packet, data_dir=Path(tmp), replayed=True)
            packet_dump.dump_packet(packet, data_dir=Path(tmp))
            self.assertEqual(len(list((Path(tmp) / "replay" / "POSITION_APP").glob("*.json"))), 1)
            self.assertEqual(len(list((Path(tmp) / "packets" / "POSITION_APP").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
