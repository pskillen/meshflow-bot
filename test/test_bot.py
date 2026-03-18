import unittest
from unittest import skipIf
from unittest.mock import MagicMock, patch

from src.bot import MeshtasticBot


class TestMeshtasticBot(unittest.TestCase):
    def setUp(self):
        self.bot = MeshtasticBot(address="localhost")
        self.bot.interface = MagicMock()

    @skipIf(True, "Not implemented")
    @patch('src.bot.pub')
    def test_connect(self, mock_pub):
        self.bot.connect()
        self.bot.interface.connect.assert_called_once()
        mock_pub.subscribe.assert_any_call(self.bot.on_receive, "meshtastic.receive")
        mock_pub.subscribe.assert_any_call(self.bot.on_receive_text, "meshtastic.receive.text")
        mock_pub.subscribe.assert_any_call(self.bot.on_node_updated, "meshtastic.node.updated")
        mock_pub.subscribe.assert_any_call(self.bot.on_connection, "meshtastic.connection.established")

    def test_disconnect(self):
        self.bot.disconnect()
        self.bot.interface.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
