from abc import ABC

from src.commands.command import AbstractCommand, AbstractCommandWithSubcommands
from src.radio.events import IncomingTextMessage
from test import BaseFeatureTestCase
from test.test_setup_data import build_test_text_message


class CommandTestCase(BaseFeatureTestCase, ABC):
    command: AbstractCommand


class CommandWSCTestCase(CommandTestCase):
    command: AbstractCommandWithSubcommands

    def assert_show_help_for_command(self, message: IncomingTextMessage):
        self.command.handle_packet(message)
        response = self.fake_radio.send_text.call_args[0][0]
        want = f"!{self.command.base_command}: "
        self.assertIn(want, response)
        for sub_command in self.command.sub_commands:
            if sub_command in ("help", ""):
                continue
            want = f"!{self.command.base_command} {sub_command}"
            self.assertIn(want, response)

    def test_show_help(self):
        if self.__class__.__name__ == 'CommandWSCTestCase':
            return
        base_cmd = self.command.base_command
        message = build_test_text_message(
            f'!{base_cmd} help', self.test_nodes[1].user.id, self.bot.my_id
        )
        self.assert_show_help_for_command(message)
