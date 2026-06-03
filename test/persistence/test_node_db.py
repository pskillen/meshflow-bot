import os
import unittest
from datetime import datetime, timezone, timedelta

from src.data_classes import MeshNode
from src.persistence.node_db import SqliteNodeDB, InMemoryNodeDB


class TestInMemoryNodeDB(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryNodeDB()
        self.node_user = MeshNode.User(
            node_id="node1", short_name="Node1", long_name="Test Node 1"
        )
        self.position = MeshNode.Position(
            logged_time=datetime.now(timezone.utc),
            latitude=10.0,
            longitude=20.0,
            altitude=100.0,
        )
        self.device_metrics = MeshNode.DeviceMetrics(
            logged_time=datetime.now(timezone.utc), battery_level=90
        )

    def test_store_and_get_user(self):
        self.db.store_user(self.node_user)
        retrieved_user = self.db.get_by_radio_id(self.node_user.id)
        self.assertEqual(retrieved_user.id, self.node_user.id)
        self.assertEqual(retrieved_user.short_name, self.node_user.short_name)
        self.assertEqual(retrieved_user.long_name, self.node_user.long_name)

    def test_store_and_get_position(self):
        self.db.store_position(self.node_user.id, self.position)
        retrieved_position = self.db.get_last_position(self.node_user.id)
        self.assertEqual(retrieved_position.latitude, self.position.latitude)
        self.assertEqual(retrieved_position.longitude, self.position.longitude)
        self.assertEqual(retrieved_position.altitude, self.position.altitude)

    def test_store_and_get_device_metrics(self):
        self.db.store_device_metrics(self.node_user.id, self.device_metrics)
        retrieved_metrics = self.db.get_last_device_metrics(self.node_user.id)
        self.assertEqual(
            retrieved_metrics.battery_level, self.device_metrics.battery_level
        )

    def test_list_nodes(self):
        self.db.store_user(self.node_user)
        nodes = self.db.list_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].id, self.node_user.id)

    def test_get_position_log(self):
        start_time = datetime.now(timezone.utc) - timedelta(days=1)
        end_time = datetime.now(timezone.utc) + timedelta(days=1)
        self.db.store_position(self.node_user.id, self.position)
        positions = self.db.get_position_log(self.node_user.id, start_time, end_time)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].latitude, self.position.latitude)

    def test_get_device_metrics_log(self):
        start_time = datetime.now(timezone.utc) - timedelta(days=1)
        end_time = datetime.now(timezone.utc) + timedelta(days=1)
        self.db.store_device_metrics(self.node_user.id, self.device_metrics)
        metrics = self.db.get_device_metrics_log(
            self.node_user.id, start_time, end_time
        )
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].battery_level, self.device_metrics.battery_level)


class TestSqliteNodeDB(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_node_db.sqlite"
        self.db = SqliteNodeDB(self.db_path)
        self.node_user = MeshNode.User(
            node_id="node1", short_name="Node1", long_name="Test Node 1"
        )
        self.position = MeshNode.Position(
            logged_time=datetime.now(timezone.utc),
            latitude=10.0,
            longitude=20.0,
            altitude=100.0,
        )
        self.device_metrics = MeshNode.DeviceMetrics(
            logged_time=datetime.now(timezone.utc), battery_level=90
        )

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_store_and_get_user(self):
        self.db.store_user(self.node_user)
        retrieved_user = self.db.get_by_radio_id(self.node_user.id)
        self.assertEqual(retrieved_user.id, self.node_user.id)
        self.assertEqual(retrieved_user.short_name, self.node_user.short_name)
        self.assertEqual(retrieved_user.long_name, self.node_user.long_name)

    def test_store_and_get_position(self):
        self.db.store_position(self.node_user.id, self.position)
        retrieved_position = self.db.get_last_position(self.node_user.id)
        self.assertEqual(retrieved_position.latitude, self.position.latitude)
        self.assertEqual(retrieved_position.longitude, self.position.longitude)
        self.assertEqual(retrieved_position.altitude, self.position.altitude)

    def test_store_and_get_device_metrics(self):
        self.db.store_device_metrics(self.node_user.id, self.device_metrics)
        retrieved_metrics = self.db.get_last_device_metrics(self.node_user.id)
        self.assertEqual(
            retrieved_metrics.battery_level, self.device_metrics.battery_level
        )

    def test_list_nodes(self):
        self.db.store_user(self.node_user)
        nodes = self.db.list_nodes()
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].id, self.node_user.id)

    def test_get_position_log(self):
        start_time = datetime.now(timezone.utc) - timedelta(days=1)
        end_time = datetime.now(timezone.utc) + timedelta(days=1)
        self.db.store_position(self.node_user.id, self.position)
        positions = self.db.get_position_log(self.node_user.id, start_time, end_time)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].latitude, self.position.latitude)

    def test_get_device_metrics_log(self):
        start_time = datetime.now(timezone.utc) - timedelta(days=1)
        end_time = datetime.now(timezone.utc) + timedelta(days=1)
        self.db.store_device_metrics(self.node_user.id, self.device_metrics)
        metrics = self.db.get_device_metrics_log(
            self.node_user.id, start_time, end_time
        )
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].battery_level, self.device_metrics.battery_level)


if __name__ == "__main__":
    unittest.main()
