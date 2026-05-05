"""Translation between Meshtastic packet dicts and the bot's typed events."""

import unittest

from src.meshtastic.translation import (
    id_to_nodenum,
    node_dict_to_mesh_node,
    node_dict_to_node_update,
    nodenum_to_id,
    packet_to_incoming,
    packet_to_text_message,
)


class TestIdConversions(unittest.TestCase):
    def test_round_trip(self):
        for nodenum in (1, 0xdeadbeef, 0xaabbccdd):
            self.assertEqual(id_to_nodenum(nodenum_to_id(nodenum)), nodenum)

    def test_id_format_is_canonical_hex(self):
        self.assertEqual(nodenum_to_id(0xaabbccdd), "!aabbccdd")
        self.assertEqual(nodenum_to_id(1), "!00000001")

    def test_id_to_nodenum_strips_leading_bang(self):
        self.assertEqual(id_to_nodenum("!aabbccdd"), 0xaabbccdd)
        self.assertEqual(id_to_nodenum("aabbccdd"), 0xaabbccdd)


class TestPacketToIncoming(unittest.TestCase):
    def test_basic_packet(self):
        packet = {
            "fromId": "!11112222",
            "toId": "!ffffffff",
            "channel": 2,
            "decoded": {"portnum": "TEXT_MESSAGE_APP"},
        }
        event = packet_to_incoming(packet, local_node_id="!aabbccdd")
        self.assertEqual(event.from_id, "!11112222")
        self.assertEqual(event.to_id, "!ffffffff")
        self.assertEqual(event.channel, 2)
        self.assertEqual(event.portnum, "TEXT_MESSAGE_APP")
        self.assertTrue(event.has_decoded)
        self.assertFalse(event.is_self_telemetry)

    def test_self_telemetry_flagged(self):
        packet = {
            "fromId": "!aabbccdd",
            "toId": "!ffffffff",
            "decoded": {
                "portnum": "TELEMETRY_APP",
                "telemetry": {"deviceMetrics": {"batteryLevel": 80}},
            },
        }
        event = packet_to_incoming(packet, local_node_id="!aabbccdd")
        self.assertTrue(event.is_self_telemetry)

    def test_undecoded_packet(self):
        packet = {"fromId": "!11112222", "toId": "!ffffffff"}
        event = packet_to_incoming(packet, local_node_id="!aabbccdd")
        self.assertFalse(event.has_decoded)
        self.assertEqual(event.portnum, "UNKNOWN")

    def test_unknown_portnum_uppercased(self):
        packet = {"decoded": {"portnum": "weirdcustom_app"}}
        event = packet_to_incoming(packet, local_node_id=None)
        self.assertEqual(event.portnum, "WEIRDCUSTOM_APP")


class TestPacketToTextMessage(unittest.TestCase):
    def test_dm_to_local_node(self):
        packet = {
            "fromId": "!11112222",
            "toId": "!aabbccdd",
            "channel": 0,
            "id": 1234,
            "hopStart": 5,
            "hopLimit": 3,
            "decoded": {"text": "hello"},
        }
        msg = packet_to_text_message(packet, local_node_id="!aabbccdd")
        self.assertEqual(msg.text, "hello")
        self.assertEqual(msg.from_id, "!11112222")
        self.assertEqual(msg.to_id, "!aabbccdd")
        self.assertTrue(msg.is_dm)
        self.assertEqual(msg.message_id, 1234)
        self.assertEqual(msg.hops_away, 2)

    def test_public_message_not_dm(self):
        packet = {
            "fromId": "!11112222",
            "toId": "^all",
            "decoded": {"text": "test"},
        }
        msg = packet_to_text_message(packet, local_node_id="!aabbccdd")
        self.assertFalse(msg.is_dm)


class TestNodeUpdate(unittest.TestCase):
    def test_full_node(self):
        data = {
            "user": {
                "id": "!11112222",
                "longName": "Alice",
                "shortName": "A",
                "macaddr": "aa:bb:cc",
                "hwModel": "T-BEAM",
                "publicKey": "pk",
            },
            "position": {"latitude": 1.0, "longitude": 2.0, "altitude": 100, "time": 1700000000},
            "deviceMetrics": {"batteryLevel": 75, "voltage": 3.9},
            "lastHeard": 1700000000,
            "isFavorite": True,
        }
        update = node_dict_to_node_update(data)
        self.assertIsNotNone(update)
        self.assertEqual(update.node.user.long_name, "Alice")
        self.assertEqual(update.node.position.altitude, 100)
        self.assertEqual(update.node.device_metrics.battery_level, 75)
        self.assertTrue(update.node.is_favorite)
        self.assertEqual(update.last_heard.year, 2023)

    def test_node_without_user_yields_none(self):
        self.assertIsNone(node_dict_to_node_update({"user": None}))

    def test_node_dict_to_mesh_node_handles_missing_fields(self):
        node = node_dict_to_mesh_node({"user": {"id": "!1"}})
        self.assertEqual(node.user.id, "!1")
        self.assertEqual(node.user.long_name, "")
        self.assertFalse(node.is_favorite)


if __name__ == "__main__":
    unittest.main()
