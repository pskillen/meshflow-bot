import unittest

from src.data_classes import MeshNode


class TestMeshNode(unittest.TestCase):

    def setUp(self):
        self.node_data = {
            "num": 1,
            "user": {
                "id": "user123",
                "longName": "Test User",
                "shortName": "TU",
                "macaddr": "00:11:22:33:44:55",
                "hwModel": "ModelX",
                "publicKey": "public_key_123",
            },
            "position": {
                "altitude": 100,
                "time": 1234567890,
                "locationSource": "GPS",
                "latitude": 37.7749,
                "longitude": -122.4194,
            },
            "lastHeard": 1234567890,
            "deviceMetrics": {
                "batteryLevel": 80,
                "voltage": 3.7,
                "channelUtilization": 0.5,
                "airUtilTx": 0.1,
                "uptimeSeconds": 3600,
            },
            "isFavorite": True,
        }

        self.mesh_node = MeshNode.from_dict(self.node_data)

    def test_from_dict(self):
        raw_data = {
            "num": 1129933592,
            "user": {
                "id": "!43596b18",
                "longName": "PDY base (unattended)",
                "shortName": "PDYb",
                "macaddr": "SMpDWWsY",
                "hwModel": "HELTEC_V3",
                "publicKey": "JWs3gfXaE1XvUm9Z2MNiC1gcGvkiFLT1/69CDCtqsxQ=",
            },
            "position": {
                "latitudeI": 558243766,
                "longitudeI": -41218138,
                "altitude": 41,
                "time": 1737237050,
                "locationSource": "LOC_EXTERNAL",
                "latitude": 55.8243766,
                "longitude": -4.1218138,
            },
            "lastHeard": 1737237050,
            "deviceMetrics": {
                "batteryLevel": 101,
                "voltage": 4.302,
                "channelUtilization": 2.915,
                "airUtilTx": 0.6213055,
                "uptimeSeconds": 372627,
            },
            "isFavorite": True,
        }

        mesh_node = MeshNode.from_dict(raw_data)

        self.assertEqual(mesh_node.user.id, "!43596b18")
        self.assertEqual(mesh_node.user.long_name, "PDY base (unattended)")
        self.assertEqual(mesh_node.position.latitude, 55.8243766)
        self.assertEqual(mesh_node.device_metrics.battery_level, 101)
        self.assertTrue(mesh_node.is_favorite)


if __name__ == "__main__":
    unittest.main()
