import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.commands.admin import AdminCommand
from src.data_classes import MeshNode
from test.commands import CommandWSCTestCase
from test.test_setup_data import build_test_text_message


class TestAdminCommand(CommandWSCTestCase):
    command: AdminCommand

    def setUp(self):
        super().setUp()
        self.command = AdminCommand(self.bot)

        self.test_nodes = sorted(self.test_nodes, key=lambda x: x.user.id)
        self._setup_nodes_mock_data(self.test_nodes)

    def _setup_nodes_mock_data(self, node_list: list[MeshNode]):
        unknown_messages = ['unknown1', 'unknown2', 'unknown3']
        self.mock_command_history = [
            {
                'sender_id': node.user.id,
                'base_command': 'cmd1' if j == 0 else 'cmd2',
                'timestamp': datetime.now(timezone.utc) - timedelta(days=i * 2 + j),
            }
            for i, node in enumerate(node_list)
            for j in range(2)
        ]
        self.mock_unknown_command_history = [
            {
                'sender_id': node.user.id,
                'message': unknown_messages[i],
                'timestamp': datetime.now(timezone.utc) - timedelta(days=i),
            }
            for i, node in enumerate(node_list)
        ]
        self.mock_responder_history = [
            {
                'sender_id': node.user.id,
                'responder_class': 'Responder1' if j == 0 else 'Responder2',
                'timestamp': datetime.now(timezone.utc) - timedelta(days=i * 2 + j),
            }
            for i, node in enumerate(node_list)
            for j in range(2)
        ]

        self.bot.command_logger.get_command_history = MagicMock(return_value=self.mock_command_history)
        self.bot.command_logger.get_unknown_command_history = MagicMock(return_value=self.mock_unknown_command_history)
        self.bot.command_logger.get_responder_history = MagicMock(return_value=self.mock_responder_history)

    def test_handle_packet_not_authorized(self):
        msg = build_test_text_message('!admin', self.test_non_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent(
            f"Sorry {self.test_non_admin_nodes[0].user.long_name}, you are not authorized to use this command",
            self.test_non_admin_nodes[0],
        )

    def test_handle_packet_authorized(self):
        msg = build_test_text_message('!admin', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent(
            "Invalid command format - expected !admin <command> <args>",
            self.test_admin_nodes[0],
        )

    def test_handle_base_command(self):
        msg = build_test_text_message('!admin', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent(
            "Invalid command format - expected !admin <command> <args>",
            self.test_admin_nodes[0],
        )

    def test_reset_packets(self):
        msg = build_test_text_message('!admin reset packets', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assertEqual(self.bot.node_info.get_all_nodes_packets_today(), {})
        self.assertEqual(self.bot.node_info.get_all_nodes_packets_today_breakdown(), {})
        self.assert_message_sent("Packet counter reset", self.test_admin_nodes[0])

    def test_reset_packets_missing_argument(self):
        msg = build_test_text_message('!admin reset', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent(
            "reset: Missing argument - options are: ['packets']",
            self.test_admin_nodes[0],
        )

    def test_reset_packets_unknown_argument(self):
        msg = build_test_text_message('!admin reset unknown', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent(
            "reset: Unknown argument 'unknown' - options are: ['packets']",
            self.test_admin_nodes[0],
        )

    def test_show_users_user_not_found(self):
        msg = build_test_text_message('!admin users !ffffff', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)
        self.assert_message_sent("User '!ffffff' not found", self.test_admin_nodes[0])

    def test_show_users_user_found(self):
        target_node = self.test_nodes[1]  # 0 is my_id
        self._setup_nodes_mock_data([target_node])
        midnight_7_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        midnight_7_days_ago = midnight_7_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)

        msg = build_test_text_message(
            f'!admin users {target_node.user.short_name}',
            self.test_admin_nodes[0].user.id,
            self.bot.my_id,
        )
        self.command.handle_packet(msg)

        summary_response = f"{target_node.user.long_name} - 2 cmds, 2 responders, 1 unknown cmds\n"
        summary_response += f"Since {midnight_7_days_ago.strftime('%Y-%m-%d %H:%M:%S')}"
        self.assert_message_sent(summary_response, self.test_admin_nodes[0], multi_response=True)

        known_commands_response = "Commands:\n"
        known_commands_response += "- cmd1: 1\n"
        known_commands_response += "- cmd2: 1\n"
        self.assert_message_sent(known_commands_response, self.test_admin_nodes[0], multi_response=True)

        unknown_commands_response = "Unknown Commands:\n"
        unknown_commands_response += "- unknown1\n"
        self.assert_message_sent(unknown_commands_response, self.test_admin_nodes[0], multi_response=True)

        responders_response = "Responders:\n"
        responders_response += "- Responder1: 1\n"
        responders_response += "- Responder2: 1\n"
        self.assert_message_sent(responders_response, self.test_admin_nodes[0], multi_response=True)

    def test_show_users_all_users(self):
        msg = build_test_text_message('!admin users', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        expected_response = f"Users: {len(self.test_nodes)}\n"
        for node in self.test_nodes:
            user_name = node.user.short_name
            expected_response += f"- {user_name}: 2 cmds, 1 unk, 2 resp\n"

        self.assert_message_sent(expected_response, self.test_admin_nodes[0])

    def test_show_help(self):
        msg = build_test_text_message('!admin help', self.test_admin_nodes[0].user.id, self.bot.my_id)
        self.assert_show_help_for_command(msg)


if __name__ == '__main__':
    unittest.main()
