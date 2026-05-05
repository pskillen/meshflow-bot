import unittest

from src.bot import MeshflowBot
from test.fake_radio import FakeRadio


class TestMeshflowBot(unittest.TestCase):
    def setUp(self):
        self.fake_radio = FakeRadio(local_node_id="!aabbccdd", local_nodenum=0xaabbccdd)
        self.bot = MeshflowBot(radio=self.fake_radio)

    def test_connect_delegates_to_radio(self):
        self.bot.connect()
        self.fake_radio.connect.assert_called_once()

    def test_disconnect_delegates_to_radio(self):
        self.bot.disconnect()
        self.fake_radio.disconnect.assert_called_once()

    def test_my_id_proxies_radio(self):
        self.assertEqual(self.bot.my_id, "!aabbccdd")
        self.assertEqual(self.bot.my_nodenum, 0xaabbccdd)

    def test_traceroute_skipped_when_disconnected(self):
        self.bot.on_traceroute_command(0x12345678)
        self.fake_radio.send_traceroute.assert_not_called()

    def test_traceroute_forwarded_when_connected(self):
        self.fake_radio._is_connected = True
        self.bot.on_traceroute_command(0x12345678)
        self.fake_radio.send_traceroute.assert_called_once_with(0x12345678)


if __name__ == '__main__':
    unittest.main()
