import unittest

from src.commands.ping import PingCommand
from test.commands import CommandTestCase
from test.test_setup_data import build_test_text_message


class TestPingCommand(CommandTestCase):
    command: PingCommand

    def setUp(self):
        super().setUp()
        self.command = PingCommand(bot=self.bot)

    def test_handle_packet_no_additional_message(self):
        message = build_test_text_message(
            '!ping', self.test_nodes[1].user.id, self.bot.my_id, max_hops=3, hops_left=3
        )
        self.command.handle_packet(message)
        self.assert_message_sent("!pong (ping took 0 hops)", self.test_nodes[1])

    def test_handle_packet_with_additional_message(self):
        message = build_test_text_message(
            '!ping extra message',
            self.test_nodes[1].user.id,
            self.bot.my_id,
            max_hops=3,
            hops_left=3,
        )
        self.command.handle_packet(message)
        self.assert_message_sent(
            "!pong: extra message (ping took 0 hops)", self.test_nodes[1]
        )

    def test_handle_packet_with_hop_count(self):
        message = build_test_text_message(
            '!ping', self.test_nodes[1].user.id, self.bot.my_id, max_hops=3, hops_left=2
        )
        self.command.handle_packet(message)
        self.assert_message_sent("!pong (ping took 1 hops)", self.test_nodes[1])


if __name__ == '__main__':
    unittest.main()
