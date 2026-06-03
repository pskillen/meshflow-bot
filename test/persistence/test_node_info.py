import unittest
from datetime import datetime, timezone, timedelta

from src.persistence.node_info import InMemoryNodeInfoStore


class TestInMemoryNodeInfoStore(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryNodeInfoStore()
        self.node_id = "node1"
        self.packet_type = "data"

    def test_node_packet_received(self):
        self.store.node_packet_received(self.node_id, self.packet_type)
        self.assertEqual(self.store.get_node_packets_today(self.node_id), 1)
        self.assertEqual(
            self.store.get_node_packets_today_breakdown(self.node_id)[self.packet_type],
            1,
        )

    def test_update_last_heard(self):
        now = datetime.now(timezone.utc)
        self.store.update_last_heard(self.node_id, now)
        self.assertEqual(self.store.get_last_heard(self.node_id), now)

    def test_reset_packets_today(self):
        self.store.node_packet_received(self.node_id, self.packet_type)
        self.store.reset_packets_today()
        self.assertEqual(self.store.get_node_packets_today(self.node_id), 0)
        self.assertEqual(self.store.get_node_packets_today_breakdown(self.node_id), {})

    def test_get_online_nodes(self):
        now = datetime.now(timezone.utc)
        self.store.update_last_heard(self.node_id, now)
        online_nodes = self.store.get_online_nodes()
        self.assertIn(self.node_id, online_nodes)

    def test_get_offline_nodes(self):
        past_time = datetime.now(timezone.utc) - timedelta(hours=3)
        self.store.update_last_heard(self.node_id, past_time)
        offline_nodes = self.store.get_offline_nodes()
        self.assertIn(self.node_id, offline_nodes)

    def test_get_all_nodes(self):
        now = datetime.now(timezone.utc)
        self.store.update_last_heard(self.node_id, now)
        all_nodes = self.store.get_all_nodes()
        self.assertIn(self.node_id, all_nodes)

    def test_get_all_nodes_packets_today(self):
        self.store.node_packet_received(self.node_id, self.packet_type)
        all_packets = self.store.get_all_nodes_packets_today()
        self.assertEqual(all_packets[self.node_id], 1)

    def test_get_all_nodes_packets_today_breakdown(self):
        self.store.node_packet_received(self.node_id, self.packet_type)
        all_packets_breakdown = self.store.get_all_nodes_packets_today_breakdown()
        self.assertEqual(all_packets_breakdown[self.node_id][self.packet_type], 1)


if __name__ == "__main__":
    unittest.main()
