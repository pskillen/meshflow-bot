import unittest

from src.commands.factory import CommandFactory
from src.commands.help import HelpCommand
from test.commands import CommandWSCTestCase
from test.test_setup_data import build_test_text_packet


class TestHelpCommand(CommandWSCTestCase):
    command: HelpCommand

    def setUp(self):
        super().setUp()
        self.command = HelpCommand(bot=self.bot)

    def test_handle_packet_no_additional_message(self):
        packet = build_test_text_packet('!help', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(packet)

        response = self.mock_interface.sendText.call_args[0][0]

        skipped_commands = []

        # Ensure every command in CommandFactory is mentioned in the response
        for command in CommandFactory.commands.keys():
            if command in skipped_commands:
                self.assertNotIn(command, response)
                print(f"Skipped command '{command}' correctly not found in response")
            else:
                self.assertIn(command, response)
                print(f"Found command '{command}' in response")

    def test_handle_packet_hello_command(self):
        packet = build_test_text_packet('!help hello', self.test_nodes[1].user.id, self.bot.my_id)
        expected_response = "!hello: responds with a greeting"

        self.command.handle_packet(packet)

        self.assert_message_sent(expected_response, self.test_nodes[1])

    def test_handle_packet_ping_command(self):
        packet = build_test_text_packet('!help ping', self.test_nodes[1].user.id, self.bot.my_id)
        expected_response = "!ping (+ optional correlation message): responds with a pong"

        self.command.handle_packet(packet)

        self.assert_message_sent(expected_response, self.test_nodes[1])

    def test_handle_packet_help_command(self):
        packet = build_test_text_packet('!help help', self.test_nodes[1].user.id, self.bot.my_id)
        expected_response = "!help: show this help message"

        self.command.handle_packet(packet)

        self.assert_message_sent(expected_response, self.test_nodes[1])

    def test_handle_packet_unknown_command(self):
        packet = build_test_text_packet('!help unknown', self.test_nodes[1].user.id, self.bot.my_id)
        expected_response = "Unknown command 'unknown'"

        self.command.handle_packet(packet)

        self.assert_message_sent(expected_response, self.test_nodes[1])

    def test_handle_packet_ping_with_and_without_exclamation(self):
        packet_with_exclamation = build_test_text_packet('!help !ping', self.test_nodes[1].user.id, self.bot.my_id)
        packet_without_exclamation = build_test_text_packet('!help ping', self.test_nodes[1].user.id, self.bot.my_id)
        expected_response = "!ping (+ optional correlation message): responds with a pong"

        self.command.handle_packet(packet_with_exclamation)
        self.assert_message_sent(expected_response, self.test_nodes[1])
        self.mock_interface.sendText.reset_mock()

        self.command.handle_packet(packet_without_exclamation)
        self.assert_message_sent(expected_response, self.test_nodes[1])

    @unittest.skip("This test comes from the base test class but doesn't make sense for this command")
    def test_show_help(self):
        pass


if __name__ == '__main__':
    unittest.main()
