import unittest
from unittest.mock import MagicMock

from src.commands.enroll import EnrollCommandHandler
from test.commands import CommandWSCTestCase
from test.test_setup_data import build_test_text_message


class TestEnrollCommandHandler(CommandWSCTestCase):
    command: EnrollCommandHandler

    def setUp(self):
        super().setUp()
        self.command = EnrollCommandHandler(self.bot, 'enroll')
        self.bot.user_prefs_persistence = MagicMock()

    def test_enroll_testing(self):
        command = EnrollCommandHandler(self.bot, 'enroll')
        sender_node = self.test_nodes[1]

        packet = build_test_text_message('!enroll testing', sender_node.user.id, self.bot.my_id)
        command.handle_packet(packet)

        self.bot.user_prefs_persistence.persist_user_prefs.assert_called_once()
        user_prefs = self.bot.user_prefs_persistence.persist_user_prefs.call_args[0][1]
        self.assertTrue(user_prefs.respond_to_testing.value)

    def test_leave_testing(self):
        command = EnrollCommandHandler(self.bot, 'leave')
        sender_node = self.test_nodes[1]

        packet = build_test_text_message('!leave testing', sender_node.user.id, self.bot.my_id)
        command.handle_packet(packet)

        self.bot.user_prefs_persistence.persist_user_prefs.assert_called_once()
        user_prefs = self.bot.user_prefs_persistence.persist_user_prefs.call_args[0][1]
        self.assertFalse(user_prefs.respond_to_testing.value)


if __name__ == '__main__':
    unittest.main()
