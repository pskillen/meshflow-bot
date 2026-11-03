"""Tests for :class:`MeshtasticPacketSerializer`."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
