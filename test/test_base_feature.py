import unittest

from meshtastic.protobuf.mesh_pb2 import MeshPacket

from src.base_feature import AbstractBaseFeature
from test.test_setup_data import build_test_text_packet, get_test_bot


class ConcreteBaseFeature(AbstractBaseFeature):
    def handle_packet(self, packet: MeshPacket) -> None:
        pass


class TestAbstractBaseFeature(unittest.TestCase):
    def setUp(self):
        self.bot, self.test_non_admin_nodes, self.test_admin_nodes = get_test_bot()
        self.feature = ConcreteBaseFeature(self.bot)
        self.mock_interface = self.bot.interface

    def test_reply_in_channel(self):
        sender = self.test_non_admin_nodes[1]
        packet = build_test_text_packet('!test', sender.user.id, self.bot.my_id, channel=1)
        self.feature.reply_in_channel(packet, "Test message")
        self.mock_interface.sendText.assert_called_once_with(
            "Test message", channelIndex=1, wantAck=False, hopLimit=5
        )

    def test_message_in_channel(self):
        self.feature.message_in_channel(1, "Test message")
        self.mock_interface.sendText.assert_called_once_with(
            "Test message", channelIndex=1, wantAck=False, hopLimit=5
        )

    def test_reply_in_dm(self):
        sender = self.test_non_admin_nodes[1]
        packet = build_test_text_packet('!test', sender.user.id, self.bot.my_id)
        self.feature.reply_in_dm(packet, "Test message")
        self.mock_interface.sendText.assert_called_once_with(
            "Test message", destinationId=sender.user.id, wantAck=False, hopLimit=5
        )

    def test_message_in_dm(self):
        sender = self.test_non_admin_nodes[1]
        self.feature.message_in_dm(sender.user.id, "Test message")
        self.mock_interface.sendText.assert_called_once_with(
            "Test message", destinationId=sender.user.id, wantAck=False, hopLimit=5
        )

    def test_react_in_channel(self):
        sender = self.test_non_admin_nodes[1]
        packet = build_test_text_packet('!test', sender.user.id, self.bot.my_id, channel=1)
        self.feature.react_in_channel(packet, "👍")
        self.mock_interface.sendReaction.assert_called_once_with("👍", messageId=packet['id'], channelIndex=1)

    def test_react_in_dm(self):
        sender = self.test_non_admin_nodes[1]
        packet = build_test_text_packet('!test', sender.user.id, self.bot.my_id)
        self.feature.react_in_dm(packet, "👍")
        self.mock_interface.sendReaction.assert_called_once_with("👍", messageId=packet['id'], destinationId=sender.user.id)


if __name__ == '__main__':
    unittest.main()
