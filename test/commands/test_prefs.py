import unittest
from unittest.mock import MagicMock

from src.commands.prefs import PrefsCommandHandler
from src.persistence.user_prefs import UserPrefs
from test.commands import CommandWSCTestCase
from test.test_setup_data import build_test_text_message


class TestPrefsCommandHandler(CommandWSCTestCase):
    command: PrefsCommandHandler

    def setUp(self):
        super().setUp()
        self.command = PrefsCommandHandler(self.bot)
        self.bot.user_prefs_persistence = MagicMock()

    def test_base_command(self):
        sender_node = self.test_nodes[1]
        self.bot.user_prefs_persistence.get_user_prefs.return_value = UserPrefs(sender_node.user.id)

        msg = build_test_text_message('!prefs', sender_node.user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        expected_response = (
            "Your preferences:\n"
            "Respond to 'testing': disabled\n"
        )
        self.assert_message_sent(expected_response, sender_node)

    def test_enable_testing(self):
        sender_node = self.test_nodes[1]
        msg = build_test_text_message('!prefs testing enable', sender_node.user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        self.bot.user_prefs_persistence.persist_user_prefs.assert_called_once()
        user_prefs = self.bot.user_prefs_persistence.persist_user_prefs.call_args[0][1]
        self.assertTrue(user_prefs.respond_to_testing.value)

        self.assert_message_sent(
            "You've enabled bot responses to 'test' or 'testing' in public channels.",
            sender_node,
        )

    def test_disable_testing(self):
        sender_node = self.test_nodes[1]
        msg = build_test_text_message('!prefs testing disable', sender_node.user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        self.bot.user_prefs_persistence.persist_user_prefs.assert_called_once()
        user_prefs = self.bot.user_prefs_persistence.persist_user_prefs.call_args[0][1]
        self.assertFalse(user_prefs.respond_to_testing.value)

        self.assert_message_sent(
            "You've disabled bot responses to 'test' or 'testing' in public channels.",
            sender_node,
        )

    def test_invalid_args(self):
        sender_node = self.test_nodes[1]
        msg = build_test_text_message('!prefs testing invalid', sender_node.user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent(
            "Invalid mode for 'testing'. Please specify 'enable' or 'disable'.",
            sender_node,
        )

    def test_invalid_pref(self):
        sender_node = self.test_nodes[1]
        msg = build_test_text_message('!prefs invalid_pref enable', sender_node.user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        expected_response = (
            "!prefs: configure bot settings related to your node:\n"
            "!prefs testing enable/disable: bot will like your msg if you say "
            "'test' or 'testing'\n"
        )
        self.assert_message_sent(expected_response, sender_node, multi_response=True)


if __name__ == '__main__':
    unittest.main()
