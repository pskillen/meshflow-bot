"""The committed 2.7/2.8 hardware-session captures (docs/meshtastic_packets/2.8) against the bot.

These pin what the bot does today with real radio output: translation,
serialisation, the upload decision per kind (live / replay / self) and the
identity facts the docs claim.
"""

import base64
import io
import json
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.bot import MeshflowBot
from src.meshtastic.replay import is_replayed
from src.meshtastic.self_telemetry import SelfTelemetryThrottle
from src.meshtastic.serializers import MeshtasticPacketSerializer
from src.meshtastic.translation import packet_to_incoming
from test.fake_radio import FakeRadio
from tools.meshtastic_fixtures import build_fixtures, check_fixtures, rules
from tools.meshtastic_fixtures.load import lib_packet, load_subset

ROOT = Path(__file__).resolve().parents[2] / "docs" / "meshtastic_packets" / "2.8"

CONTRACT_KEYS = [row[0] for row in build_fixtures.SUBSET]


def _entries():
    return load_subset(ROOT)


def _event(entry):
    num = entry["feeder_num"]
    return packet_to_incoming(
        lib_packet(entry), local_node_id=rules.node_id_str(num), local_nodenum=num
    )


def _bot(entry, mode="drop"):
    num = entry["feeder_num"]
    bot = MeshflowBot(
        radio=FakeRadio(local_node_id=rules.node_id_str(num), local_nodenum=num)
    )
    bot.replayed_packets_mode = mode
    api = MagicMock()
    bot.storage_apis = [api]
    bot.node_db = MagicMock()
    bot.node_info = MagicMock()
    return bot, api


def _deliver(bot, entry):
    with patch("src.bot.dump_packet"):
        bot._on_packet(_event(entry))


def _has_key(obj, name):
    if isinstance(obj, dict):
        return name in obj or any(_has_key(v, name) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, name) for v in obj)
    return False


class TestCheckerOnCommittedTree(unittest.TestCase):
    def test_check_passes(self):
        ok, problems = check_fixtures.check_tree(ROOT)
        self.assertEqual(problems, [])
        self.assertEqual(len([line for line in ok if "subset" not in line]), 9)

    def test_main_exit_code_and_one_ok_line_per_capture(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = check_fixtures.main([str(ROOT)])
        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertTrue(all(line.startswith("OK ") for line in lines), lines)
        self.assertEqual(len(lines), 10)

    def test_pending_slots_are_listed_and_have_no_directory(self):
        index = json.loads((ROOT / "captures.json").read_text())
        pending = [e for e in index if e["status"] == "pending"]
        self.assertEqual(
            {e["id"] for e in pending},
            {"pdyb-2.7-x-2.8-sender", "tm-dedup", "new-ports"},
        )
        for entry in pending:
            self.assertFalse((ROOT / "captures" / entry["id"]).exists())


class TestSubset(unittest.TestCase):
    def test_contract_keys_are_all_present_and_unique(self):
        keys = [e["key"] for e in _entries()]
        self.assertEqual(len(keys), len(set(keys)))
        # The 36 Xiao rows are frozen (api goldens read them); the PDYt rows are additions.
        self.assertEqual(len(CONTRACT_KEYS), 55)
        self.assertEqual(set(CONTRACT_KEYS) - set(keys), set())
        self.assertEqual(
            [k for k in CONTRACT_KEYS if k.split("-L")[0] in build_fixtures.FROZEN_SHORTS],
            CONTRACT_KEYS[:36],
        )

    def test_known_facts_behind_the_labels(self):
        by_key = {e["key"]: e for e in _entries()}
        self.assertEqual(by_key["x28-L4"]["id"], by_key["x28h4-L4"]["id"])
        self.assertEqual(by_key["x28-L4"]["id"], 3909798862)
        self.assertIn("fake-direct", by_key["x28-L4"]["labels"])
        self.assertIn("stable-replay-id", by_key["x28h4-L4"]["labels"])
        self.assertEqual(by_key["x28h4-L4"]["record"]["packet"]["hopStart"], 4)
        self.assertEqual(
            by_key["x28f-L4"]["record"]["packet"]["decoded"]["position"]["precisionBits"], 13
        )
        self.assertIn("sender-id:crc32", by_key["x28-L85"]["labels"])
        self.assertIn("no-rx-time", by_key["x28f-L1"]["labels"])
        self.assertNotIn("decoded", by_key["x27-L37"]["record"]["packet"])
        self.assertIn("port:ENCRYPTED", by_key["x27-L37"]["labels"])
        # The Xiao rows never gain the pki-encrypted label (x28h4-L1 is pkiEncrypted).
        self.assertTrue(by_key["x28h4-L1"]["record"]["packet"]["pkiEncrypted"])
        self.assertNotIn("pki-encrypted", by_key["x28h4-L1"]["labels"])

    def test_pdyt_rows(self):
        by_key = {e["key"]: e for e in _entries()}
        signed = by_key["p28s-L16"]
        self.assertIs(signed["record"]["packet"]["xeddsaSigned"], True)
        self.assertIn("signed", signed["labels"])
        self.assertEqual([k for k, e in by_key.items() if "signed" in e["labels"]], ["p28s-L16"])
        for key in ("p28d-L55", "p28d-L58"):
            self.assertIn("pki-encrypted", by_key[key]["labels"])
            self.assertTrue(by_key[key]["record"]["packet"]["pkiEncrypted"])
        self.assertEqual(by_key["p28d-L55"]["record"]["packet"]["decoded"]["text"], "fx1 D")
        self.assertEqual(by_key["p28d-L58"]["port"], "PAGING_APP")
        self.assertEqual(by_key["p28-L9"]["feeder_num"], 2304338203)
        self.assertEqual(by_key["p27-L1"]["feeder_num"], 1127973616)
        self.assertIn("feeder:2.7", by_key["p27-L4"]["labels"])
        self.assertIn("fake-direct", by_key["p28-L55"]["labels"])
        for key in ("p28-L8", "p28-L9", "p28-L10"):
            self.assertIn("sender-id:mac", by_key[key]["labels"])


class TestTranslationAndSerialiser(unittest.TestCase):
    def test_every_entry_builds_an_event_and_serialises(self):
        serialiser = MeshtasticPacketSerializer()
        for entry in _entries():
            with self.subTest(entry["key"]):
                event = _event(entry)
                self.assertEqual(event.replayed, entry["kind"] == "replay")
                self.assertEqual(
                    event.has_decoded, entry["port"] != "ENCRYPTED"
                )
                with patch(
                    "src.meshtastic.serializers.time",
                    **{"time.return_value": entry["t_host"]},
                ):
                    body = serialiser.serialise_raw_packet(lib_packet(entry))
                json.dumps(body)
                self.assertFalse(_has_key(body, "raw"))
                self.assertTrue(body["rxTime"])
                original = entry["record"]["packet"].get("rxTime")
                self.assertEqual(body["rxTime"], original or int(entry["t_host"]))
                self.assertEqual(
                    body["channel"], entry["record"]["packet"].get("channel", 0)
                )


class TestUploadDecision(unittest.TestCase):
    def _by_kind(self, kind, decoded=True):
        return [
            e
            for e in _entries()
            if e["kind"] == kind and (e["port"] != "ENCRYPTED") == decoded
        ]

    def test_live_decoded_is_uploaded_once(self):
        for entry in self._by_kind("live"):
            with self.subTest(entry["key"]):
                bot, api = _bot(entry)
                _deliver(bot, entry)
                api.store_raw_packet.assert_called_once()
                self.assertNotIn("replayed", api.store_raw_packet.call_args.args[0])

    def test_encrypted_is_never_uploaded(self):
        encrypted = self._by_kind("live", decoded=False)
        self.assertTrue(any(e["key"] == "x27-L37" for e in encrypted))
        for entry in encrypted:
            bot, api = _bot(entry)
            _deliver(bot, entry)
            api.store_raw_packet.assert_not_called()

    def test_replay_dropped_by_default(self):
        for entry in self._by_kind("replay"):
            with self.subTest(entry["key"]):
                bot, api = _bot(entry, "drop")
                _deliver(bot, entry)
                api.store_raw_packet.assert_not_called()
                bot.node_info.node_packet_received.assert_not_called()

    def test_replay_flagged_when_asked(self):
        for entry in self._by_kind("replay"):
            with self.subTest(entry["key"]):
                bot, api = _bot(entry, "flag")
                _deliver(bot, entry)
                api.store_raw_packet.assert_called_once()
                self.assertIs(api.store_raw_packet.call_args.args[0]["replayed"], True)

    def test_self_telemetry_waits_for_the_throttle(self):
        telemetry = [e for e in self._by_kind("self") if e["port"] == "TELEMETRY_APP"]
        self.assertGreaterEqual(len(telemetry), 6)
        for entry in telemetry:
            with self.subTest(entry["key"]):
                bot, api = _bot(entry)
                bot.self_telemetry = SelfTelemetryThrottle(900)
                _deliver(bot, entry)
                api.store_raw_packet.assert_not_called()
                self.assertEqual(len(bot.self_telemetry.flush()), 1)
                # Without a throttle the sample is simply not uploaded.
                bot2, api2 = _bot(entry)
                _deliver(bot2, entry)
                api2.store_raw_packet.assert_not_called()

    def test_self_routing_ack_is_uploaded_today(self):
        # Current behaviour, not an endorsement: the feeder's own ROUTING ACK is
        # a decoded non-telemetry packet, so it goes through the normal path.
        acks = [e for e in self._by_kind("self") if e["port"] == "ROUTING_APP"]
        self.assertEqual({e["key"] for e in acks}, {"x28h4-L1", "x28f-L8"})
        for entry in acks:
            with self.subTest(entry["key"]):
                bot, api = _bot(entry)
                _deliver(bot, entry)
                api.store_raw_packet.assert_called_once()


class TestClassifier(unittest.TestCase):
    def test_bot_classifier_agrees_with_kind_on_every_record(self):
        index = json.loads((ROOT / "captures.json").read_text())
        total = 0
        for entry in index:
            if entry["status"] != "captured":
                continue
            cdir = ROOT / entry["path"]
            feeder = json.loads((cdir / "manifest.json").read_text())["feeder"]["num"]
            for rec in build_fixtures.load_capture_records(cdir):
                total += 1
                self.assertEqual(
                    is_replayed(rec["packet"], feeder),
                    rec["kind"] == "replay",
                    f"{entry['id']} line {rec['src_line']}",
                )
        self.assertEqual(total, 63 + 135 + 89 + 128 + 24 + 67 + 26 + 156 + 63)


class TestIdentityFacts(unittest.TestCase):
    def _identity(self, name):
        return json.loads((ROOT / "identity" / name).read_text())

    @staticmethod
    def _crc(identity):
        return zlib.crc32(base64.b64decode(identity["pubkey_b64"])) & 0xFFFFFFFF

    def test_2_8_numbers_are_crc32_of_the_key(self):
        for name in ("niav_2.8.json", "niav_2.8_rekeyed.json", "niav_2.8_after_reupgrade.json"):
            with self.subTest(name):
                ident = self._identity(name)
                self.assertEqual(self._crc(ident), ident["num"])
                self.assertTrue(ident["match"])

    def test_downgrade_keeps_the_crc32_number(self):
        ident = self._identity("niav_2.7_after_downgrade.json")
        self.assertEqual(self._crc(ident), ident["num"])

    def test_2_7_number_is_not_crc32_of_the_key(self):
        ident = self._identity("niav_2.7.json")
        self.assertNotEqual(self._crc(ident), ident["num"])
        self.assertFalse(ident["match"])
        # Same key, and the update moves the number to its crc32.
        self.assertEqual(ident["pubkey_b64"], self._identity("niav_2.8.json")["pubkey_b64"])
        self.assertEqual(self._crc(ident), self._identity("niav_2.8.json")["num"])

    def test_rekey_prediction_matches(self):
        predicted = (ROOT / "identity" / "rekey_predicted.txt").read_text().strip()
        self.assertEqual(predicted, self._identity("niav_2.8_rekeyed.json")["id"])

    def test_pdyt_update_moves_the_number_and_keeps_the_mac(self):
        before = self._identity("pdyt_2.7.json")
        after = self._identity("pdyt_2.8.json")
        self.assertEqual(before["pubkey_b64"], after["pubkey_b64"])
        self.assertEqual(self._crc(before), after["num"])
        self.assertEqual(self._crc(after), after["num"])
        self.assertNotEqual(self._crc(before), before["num"])
        self.assertFalse(before["match"])
        self.assertTrue(after["match"])
        # The 2.7 number is the last four bytes of the MAC; the MAC survives the update.
        mac = base64.b64decode(before["macaddr"])
        self.assertEqual(int.from_bytes(mac[2:], "big"), before["num"])
        self.assertEqual(after["macaddr"], before["macaddr"])

    def test_wild_2_8_sender_matches(self):
        entry = next(e for e in _entries() if e["key"] == "x28-L85")
        packet = entry["record"]["packet"]
        self.assertEqual(rules.node_id_str(packet["from"]), "!23c3c49f")
        key = packet["decoded"]["user"]["publicKey"]
        self.assertEqual(rules.crc32_of_pubkey(key), packet["from"])


if __name__ == "__main__":
    unittest.main()
