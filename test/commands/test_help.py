import unittest

from src.commands.factory import CommandFactory
from src.commands.help import HelpCommand
from test.commands import CommandWSCTestCase
from test.test_setup_data import build_test_text_message


class TestHelpCommand(CommandWSCTestCase):
    command: HelpCommand

    def setUp(self):
        super().setUp()
        self.command = HelpCommand(bot=self.bot)

    def test_handle_packet_no_additional_message(self):
        message = build_test_text_message('!help', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(message)

        response = self.fake_radio.send_text.call_args[0][0]
        skipped_commands = ['!admin']
        for command in CommandFactory.commands.keys():
            if command in skipped_commands:
                self.assertNotIn(command, response)
            else:
                self.assertIn(command, response)

    def test_handle_packet_hello_command(self):
        message = build_test_text_message('!help hello', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(message)
        self.assert_message_sent("!hello: responds with a greeting", self.test_nodes[1])

    def test_handle_packet_ping_command(self):
        message = build_test_text_message('!help ping', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(message)
        self.assert_message_sent(
            "!ping (+ optional correlation message): responds with a pong",
            self.test_nodes[1],
        )

    def test_handle_packet_help_command(self):
        message = build_test_text_message('!help help', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(message)
        self.assert_message_sent("!help: show this help message", self.test_nodes[1])

    def test_handle_packet_unknown_command(self):
        message = build_test_text_message('!help unknown', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(message)
        self.assert_message_sent("Unknown command 'unknown'", self.test_nodes[1])

    def test_handle_packet_ping_with_and_without_exclamation(self):
        with_excl = build_test_text_message('!help !ping', self.test_nodes[1].user.id, self.bot.my_id)
        without_excl = build_test_text_message('!help ping', self.test_nodes[1].user.id, self.bot.my_id)
        expected = "!ping (+ optional correlation message): responds with a pong"

        self.command.handle_packet(with_excl)
        self.assert_message_sent(expected, self.test_nodes[1])
        self.fake_radio.send_text.reset_mock()

        self.command.handle_packet(without_excl)
        self.assert_message_sent(expected, self.test_nodes[1])

    @unittest.skip("Not applicable to !help (its sub-commands self-describe)")
    def test_show_help(self):
        pass


if __name__ == '__main__':
    unittest.main()
