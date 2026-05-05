import unittest

from src.commands.command import AbstractCommand, AbstractCommandWithSubcommands
from src.radio.events import IncomingTextMessage
from test.commands import CommandTestCase, CommandWSCTestCase
from test.test_setup_data import build_test_text_message


class ConcreteCommand(AbstractCommand):
    def handle_packet(self, message: IncomingTextMessage) -> None:
        self.reply(message, "Handled")

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_command_and_args(message)


class ConcreteCommandWithSubcommands(AbstractCommandWithSubcommands):
    def handle_base_command(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "Base command handled")

    def show_help(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "Help shown")

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_onesub_args(message)


class TestAbstractCommand(CommandTestCase):
    command: ConcreteCommand

    def setUp(self):
        super().setUp()
        self.command = ConcreteCommand(bot=self.bot, base_command="test")

    def test_handle_packet(self):
        msg = build_test_text_message('!test', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent("Handled", self.test_nodes[1])

    def test_reply(self):
        msg = build_test_text_message('!test', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.reply(msg, "Reply message")
        self.assert_message_sent("Reply message", self.test_nodes[1])


class TestAbstractCommandWithSubcommands(CommandWSCTestCase):
    command: ConcreteCommandWithSubcommands

    def setUp(self):
        super().setUp()
        self.command = ConcreteCommandWithSubcommands(bot=self.bot, base_command_str="test")

    def test_handle_base_command(self):
        msg = build_test_text_message('!test', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent("Base command handled", self.test_nodes[1])

    def test_show_help(self):
        msg = build_test_text_message('!test help', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent("Help shown", self.test_nodes[1])

    def test_unknown_subcommand(self):
        msg = build_test_text_message('!test unknown', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent("Unknown command 'unknown'", self.test_nodes[1])


if __name__ == '__main__':
    unittest.main()
