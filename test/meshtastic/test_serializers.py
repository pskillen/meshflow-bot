"""Tests for :class:`MeshtasticPacketSerializer`."""

import base64
import copy
import json
import unittest
from pathlib import Path

from meshtastic.protobuf import mesh_pb2

from src.data_classes import MeshNode
from src.meshtastic.serializers import MeshtasticPacketSerializer


class TestMeshtasticPacketSerializer(unittest.TestCase):
    def setUp(self):
        self.serializer = MeshtasticPacketSerializer()

    def test_serialise_raw_packet_strips_raw_field(self):
        packet = {"fromId": "!1", "raw": object(), "decoded": {"text": "hi"}}
        out = self.serializer.serialise_raw_packet(packet)
        self.assertNotIn("raw", out)
        self.assertEqual(out["decoded"]["text"], "hi")

    def test_serialise_raw_packet_base64_encodes_bytes(self):
        packet = {"fromId": "!1", "decoded": {"payload": b"hello"}}
        out = self.serializer.serialise_raw_packet(packet)
        self.assertEqual(out["decoded"]["payload"], "aGVsbG8=")

    def test_serialise_raw_packet_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            self.serializer.serialise_raw_packet("nope")

    def test_serialise_node_round_trip(self):
        node = MeshNode()
        node.user = MeshNode.User(
            node_id="!12345678",
            long_name="Alice",
            short_name="A",
            macaddr="aa:bb:cc",
            hw_model="T-BEAM",
            public_key="pk",
        )
        node.position = None
        node.device_metrics = None
        out = self.serializer.serialise_node(node)
        self.assertEqual(out["id"], "!12345678")
        self.assertEqual(out["user"]["long_name"], "Alice")
        # round-trip back
        node2 = self.serializer.deserialise_node(out)
        self.assertEqual(node2.user.id, "!12345678")
        self.assertEqual(node2.user.long_name, "Alice")

    def test_serialise_node_uses_meshtastic_api_field_names(self):
        import datetime

        node = MeshNode()
        node.user = MeshNode.User(node_id="!abcdef12", long_name="Bob", short_name="B")
        node.position = MeshNode.Position(
            logged_time=datetime.datetime(
                2026, 5, 22, 7, 0, 0, tzinfo=datetime.timezone.utc
            ),
            reported_time=datetime.datetime(
                2026, 5, 22, 7, 0, 0, tzinfo=datetime.timezone.utc
            ),
            latitude=51.5,
            longitude=-0.1,
            altitude=10,
            location_source="",
        )
        node.device_metrics = MeshNode.DeviceMetrics(
            logged_time=datetime.datetime(
                2026, 5, 22, 7, 0, 0, tzinfo=datetime.timezone.utc
            ),
            channel_utilization=None,
            air_util_tx=None,
        )
        out = self.serializer.serialise_node(node)
        self.assertEqual(out["position"]["meshtastic_location_source"], "UNSET")
        self.assertNotIn("location_source", out["position"])
        self.assertEqual(out["device_metrics"]["meshtastic_channel_utilization"], 0.0)
        self.assertEqual(out["device_metrics"]["meshtastic_air_util_tx"], 0.0)
        self.assertNotIn("channel_utilization", out["device_metrics"])
        self.assertNotIn("air_util_tx", out["device_metrics"])

    def _node_with_last_heard(self, last_heard):
        node = MeshNode()
        node.user = MeshNode.User(node_id="!1", long_name="A", short_name="A")
        node.position = None
        node.device_metrics = None
        node.last_heard = last_heard
        return node

    def test_serialise_node_sends_last_heard_iso_utc(self):
        from datetime import datetime, timezone

        node = self._node_with_last_heard(
            datetime.fromtimestamp(1700000000, timezone.utc)
        )
        out = self.serializer.serialise_node(node)
        self.assertEqual(out["last_heard"], "2023-11-14T22:13:20+00:00")

    def test_serialise_node_omits_last_heard_when_missing(self):
        out = self.serializer.serialise_node(self._node_with_last_heard(None))
        self.assertNotIn("last_heard", out)


SIG = bytes(range(64))
_DATA = b"\x08\x01\x52\x40" + SIG
SIGNED_BYTES = b"\x22" + bytes([len(_DATA)]) + _DATA + b"\xb0\x01\x01\xb8\x01\x01"
UNSIGNED_BYTES = b"\x08\x05"
SUBSET = Path(__file__).resolve().parents[2] / "docs/meshtastic_packets/2.8/subset.json"


def _proto(raw: bytes):
    pkt = mesh_pb2.MeshPacket()
    pkt.ParseFromString(raw)
    return pkt


def _packet(raw: bytes, **extra):
    return {
        "fromId": "!1",
        "rxTime": 1,
        "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hi"},
        "raw": _proto(raw),
        **extra,
    }


class TestSigningFields(unittest.TestCase):
    def test_signed_adds_all_fields(self):
        out = MeshtasticPacketSerializer().serialise_raw_packet(_packet(SIGNED_BYTES))
        self.assertIs(out["xeddsaSigned"], True)
        self.assertEqual(
            out["decoded"]["xeddsaSignature"], base64.b64encode(SIG).decode()
        )
        self.assertEqual(out["ackProofStatus"], "ACK_PROOF_VALID")

    def test_unsigned_false_on_2_8_firmware(self):
        s = MeshtasticPacketSerializer(firmware_version=lambda: "2.8.2.d5f1619")
        out = s.serialise_raw_packet(_packet(UNSIGNED_BYTES))
        self.assertIs(out["xeddsaSigned"], False)
        self.assertNotIn("ackProofStatus", out)
        self.assertNotIn("xeddsaSignature", out["decoded"])

    def test_unsigned_absent_when_unknown(self):
        for fw in (lambda: "2.7.26.abc", lambda: None, lambda: "garbage", None):
            s = MeshtasticPacketSerializer(firmware_version=fw)
            out = s.serialise_raw_packet(_packet(UNSIGNED_BYTES))
            self.assertNotIn("xeddsaSigned", out)

    def test_signed_true_even_on_old_firmware_string(self):
        s = MeshtasticPacketSerializer(firmware_version=lambda: "2.7.26.abc")
        out = s.serialise_raw_packet(_packet(SIGNED_BYTES))
        self.assertIs(out["xeddsaSigned"], True)

    def test_ack_proof_zero_is_absent(self):
        out = MeshtasticPacketSerializer().serialise_raw_packet(
            _packet(b"\xb8\x01\x00")
        )
        self.assertNotIn("ackProofStatus", out)

    def test_existing_dict_key_wins(self):
        packet = _packet(SIGNED_BYTES, xeddsaSigned=False)
        out = MeshtasticPacketSerializer().serialise_raw_packet(packet)
        self.assertIs(out["xeddsaSigned"], False)
        self.assertNotIn("ackProofStatus", out)
        self.assertNotIn("xeddsaSignature", out["decoded"])

    def test_failure_never_stops_upload(self):
        class Boom:
            channel = 0

            def SerializeToString(self):
                raise RuntimeError("boom")

        packet = {"fromId": "!1", "rxTime": 1, "raw": Boom()}
        out = MeshtasticPacketSerializer(
            firmware_version=lambda: "2.8.2"
        ).serialise_raw_packet(packet)
        self.assertEqual(out["fromId"], "!1")

    def test_firmware_callable_raising_is_absent(self):
        def bad():
            raise RuntimeError("disconnected")

        out = MeshtasticPacketSerializer(firmware_version=bad).serialise_raw_packet(
            _packet(UNSIGNED_BYTES)
        )
        self.assertNotIn("xeddsaSigned", out)

    def test_subset_output_unchanged(self):
        """Every 2.8 fixture record serialises as before: with or without the
        raw protobuf and no firmware callback, nothing is added."""
        records = json.loads(SUBSET.read_text(encoding="utf-8"))
        self.assertTrue(records)
        serializer = MeshtasticPacketSerializer()
        for entry in records:
            rec = entry["record"]
            baseline = serializer.serialise_raw_packet(copy.deepcopy(rec["packet"]))
            with_raw = copy.deepcopy(rec["packet"])
            with_raw["raw"] = _proto(base64.b64decode(rec["raw_b64"]))
            out = serializer.serialise_raw_packet(with_raw)
            # the existing raw-protobuf channel backfill is not ours
            out.pop("channel", None)
            baseline.pop("channel", None)
            self.assertEqual(out, baseline, entry["id"])
            for key in ("xeddsaSigned", "ackProofStatus"):
                self.assertNotIn(key, baseline)


if __name__ == "__main__":
    unittest.main()
