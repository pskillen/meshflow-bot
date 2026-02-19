import unittest
from unittest.mock import MagicMock, call
from src.commands.tr import TracerouteCommand
from test.commands import CommandTestCase
from test.test_setup_data import build_test_text_packet

class TestTracerouteCommand(CommandTestCase):
    command: TracerouteCommand

    def setUp(self):
        super().setUp()
        self.command = TracerouteCommand(bot=self.bot)
        # Mock sendTraceRoute since it's used in handle_packet
        self.bot.interface.sendTraceRoute = MagicMock()

    def test_handle_packet_basic(self):
        # !tr from node 1
        sender_id = self.test_nodes[1].user.id
        packet = build_test_text_packet('!tr', sender_id, self.bot.my_id)
        packet['hopStart'] = 3
        packet['hopLimit'] = 2
        # Ensure we know the SNR for the test
        packet['rxSnr'] = 5.5
        
        self.command.handle_packet(packet)
        
        # Check starting message sent to sender
        expected_msg = f"{self.test_nodes[1].user.long_name} you are 1 hops away (Signal: 5.5 dB). Starting full traceroute..."
        self.mock_interface.sendText.assert_any_call(expected_msg, destinationId=sender_id, wantAck=True)
        
        # Check sendTraceRoute called for sender
        self.bot.interface.sendTraceRoute.assert_called_once_with(sender_id, hopLimit=7)
        
        # Check pending_traces entry
        self.assertEqual(self.bot.pending_traces[sender_id], [sender_id])

    def test_handle_packet_zero_hops(self):
        sender_id = self.test_nodes[1].user.id
        packet = build_test_text_packet('!tr', sender_id, self.bot.my_id)
        packet['hopStart'] = 3
        packet['hopLimit'] = 3
        
        self.command.handle_packet(packet)
        
        # Check zero hops message
        expected_msg = f"{self.test_nodes[1].user.long_name} you are Zero Hops from me. No traceroute required!"
        self.mock_interface.sendText.assert_any_call(expected_msg, destinationId=sender_id, wantAck=True)
        self.bot.interface.sendTraceRoute.assert_not_called()

    def test_handle_packet_to_specific_node(self):
        # Requester is node 1, Target is node 2
        requester_id = self.test_nodes[1].user.id
        target_node = self.test_nodes[2]
        target_short = target_node.user.short_name
        
        packet = build_test_text_packet(f'!tr {target_short}', requester_id, self.bot.my_id)
        
        self.command.handle_packet(packet)
        
        expected_msg = f"Starting traceroute to {target_node.user.long_name} ({target_node.user.id}) for you..."
        self.mock_interface.sendText.assert_any_call(expected_msg, destinationId=requester_id, wantAck=True)
        
        self.bot.interface.sendTraceRoute.assert_called_once_with(target_node.user.id, hopLimit=7)
        self.assertEqual(self.bot.pending_traces[target_node.user.id], [requester_id])

    def test_handle_packet_unknown_shortname(self):
        requester_id = self.test_nodes[1].user.id
        packet = build_test_text_packet('!tr NONEXIST', requester_id, self.bot.my_id)
        
        self.command.handle_packet(packet)
        
        expected_msg = "Could not find node with short name 'NONEXIST'"
        self.mock_interface.sendText.assert_any_call(expected_msg, destinationId=requester_id, wantAck=True)
        self.bot.interface.sendTraceRoute.assert_not_called()

    def test_handle_packet_to_self(self):
        # Bot's ID is typically !00000001 in test setup
        requester_id = self.test_nodes[1].user.id
        # We need the bot's short name if we want to test by shortname, 
        # but the command specifically checks against self.bot.my_id.
        # Let's find a way to trigger the "I am already here" message.
        
        # Manually find/set a short name for the bot if needed, or just use words[1]
        self.bot.get_node_by_short_name = MagicMock(return_value=MagicMock(id=self.bot.my_id, long_name="Bot"))
        
        packet = build_test_text_packet('!tr BOT', requester_id, self.bot.my_id)
        self.command.handle_packet(packet)
        
        expected_msg = "I am already here! No traceroute required."
        self.mock_interface.sendText.assert_any_call(expected_msg, destinationId=requester_id, wantAck=True)

if __name__ == '__main__':
    unittest.main()
