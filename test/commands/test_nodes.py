import unittest

from src.commands.nodes import NodesCommand
from src.helpers import pretty_print_last_heard
from test.commands import CommandWSCTestCase
from test.test_setup_data import build_test_text_message


class TestNodesCommand(CommandWSCTestCase):
    command: NodesCommand

    def setUp(self):
        super().setUp()
        self.command = NodesCommand(self.bot)
        self.online_count = len(self.bot.node_info.get_online_nodes())
        self.offline_count = len(self.bot.node_info.get_offline_nodes())

    def test_handle_base_command(self):
        msg = build_test_text_message('!nodes', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        expected_response = (
            f"{self.online_count} nodes online, {self.offline_count} offline.\n"
            "Recent nodes:\n"
        )

        all_nodes = sorted(
            self.test_nodes,
            key=lambda n: self.bot.node_info.get_last_heard(n.user.id),
            reverse=True,
        )

        for node in all_nodes[:5]:
            last_heard = self.bot.node_info.get_last_heard(node.user.id)
            friendly_time = pretty_print_last_heard(last_heard)
            expected_response += f"- {node.user.short_name} ({friendly_time})\n"

        self.assert_message_sent(expected_response, self.test_nodes[1])

    def test_handle_busy_command(self):
        msg = build_test_text_message('!nodes busy', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        sorted_nodes = sorted(
            self.bot.node_info.get_all_nodes_packets_today().items(),
            key=lambda x: x[1],
            reverse=True,
        )

        expected_response = f"{self.online_count} nodes online.\nBusy nodes:\n"
        for node_id, packet_count in sorted_nodes[:5]:
            node = self.bot.node_db.get_by_id(node_id)
            expected_response += f"- {node.short_name} ({packet_count} pkts)\n"

        last_reset_time = self.bot.node_info.packet_counter_reset_time.strftime("%H:%M:%S")
        expected_response += f"(last reset at {last_reset_time})"

        self.assert_message_sent(expected_response, self.test_nodes[1])

    def test_handle_busy_detailed_command(self):
        msg = build_test_text_message('!nodes busy detailed', self.test_nodes[1].user.id, self.bot.my_id)
        self.command.handle_packet(msg)

        self.fake_radio.send_text.assert_called()
        self.assertEqual(self.fake_radio.send_text.call_count, 3)

    def test_handle_busy_specific_node(self):
        target_node = self.test_nodes[1]
        msg = build_test_text_message(
            f'!nodes busy {target_node.user.short_name}',
            self.test_nodes[1].user.id,
            self.bot.my_id,
        )
        self.command.handle_packet(msg)

        packets_today = self.bot.node_info.get_node_packets_today(target_node.user.id)
        packet_breakdown_today = self.bot.node_info.get_node_packets_today_breakdown(
            target_node.user.id
        )
        last_heard = self.bot.node_info.get_last_heard(target_node.user.id)

        expected_response = f"{target_node.user.long_name} ({target_node.user.short_name})\n"
        expected_response += f"Last heard: {pretty_print_last_heard(last_heard)}\n"
        expected_response += f"Pkts today: {packets_today}\n"

        sorted_breakdown = sorted(packet_breakdown_today.items(), key=lambda x: x[1], reverse=True)
        for packet_type, count in sorted_breakdown:
            expected_response += f"- {packet_type}: {count}\n"

        self.assert_message_sent(expected_response, self.test_nodes[1])


if __name__ == '__main__':
    unittest.main()
