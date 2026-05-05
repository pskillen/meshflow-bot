import unittest

from src.base_feature import AbstractBaseFeature
from src.radio.events import IncomingTextMessage
from test.test_setup_data import build_test_text_message, get_test_bot


class ConcreteBaseFeature(AbstractBaseFeature):
    def handle_packet(self, message: IncomingTextMessage) -> None:
        pass


class TestAbstractBaseFeature(unittest.TestCase):
    def setUp(self):
        self.bot, self.test_non_admin_nodes, self.test_admin_nodes = get_test_bot()
        self.feature = ConcreteBaseFeature(self.bot)
        self.fake_radio = self.bot.radio

    def test_reply_in_channel(self):
        sender = self.test_non_admin_nodes[1]
        msg = build_test_text_message('!test', sender.user.id, self.bot.my_id, channel=1)
        self.feature.reply_in_channel(msg, "Test message")
        self.fake_radio.send_text.assert_called_once_with(
            "Test message", channel=1, want_ack=False, hop_limit=5
        )

    def test_message_in_channel(self):
        self.feature.message_in_channel(1, "Test message")
        self.fake_radio.send_text.assert_called_once_with(
            "Test message", channel=1, want_ack=False, hop_limit=5
        )

    def test_reply_in_dm(self):
        sender = self.test_non_admin_nodes[1]
        msg = build_test_text_message('!test', sender.user.id, self.bot.my_id)
        self.feature.reply_in_dm(msg, "Test message")
        self.fake_radio.send_text.assert_called_once_with(
            "Test message", destination_id=sender.user.id, want_ack=False, hop_limit=5
        )

    def test_message_in_dm(self):
        sender = self.test_non_admin_nodes[1]
        self.feature.message_in_dm(sender.user.id, "Test message")
        self.fake_radio.send_text.assert_called_once_with(
            "Test message", destination_id=sender.user.id, want_ack=False, hop_limit=5
        )

    def test_react_in_channel(self):
        sender = self.test_non_admin_nodes[1]
        msg = build_test_text_message('!test', sender.user.id, self.bot.my_id, channel=1)
        self.feature.react_in_channel(msg, "👍")
        self.fake_radio.send_reaction.assert_called_once_with(
            "👍", msg.message_id, channel=1
        )

    def test_react_in_dm(self):
        sender = self.test_non_admin_nodes[1]
        msg = build_test_text_message('!test', sender.user.id, self.bot.my_id)
        self.feature.react_in_dm(msg, "👍")
        self.fake_radio.send_reaction.assert_called_once_with(
            "👍", msg.message_id, destination_id=sender.user.id
        )


if __name__ == '__main__':
    unittest.main()
