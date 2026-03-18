import unittest
from abc import ABC
from unittest.mock import Mock

from src.bot import MeshtasticBot
from src.data_classes import MeshNode
from test.test_setup_data import get_test_bot


class BaseFeatureTestCase(unittest.TestCase, ABC):
    bot: MeshtasticBot
    mock_interface: Mock
    test_admin_nodes: list[MeshNode] = []
    test_non_admin_nodes: list[MeshNode] = []
    test_nodes: list[MeshNode] = []

    def setUp(self):
        self.bot, self.test_non_admin_nodes, self.test_admin_nodes = get_test_bot()
        self.test_nodes = self.test_non_admin_nodes + self.test_admin_nodes
        self.mock_interface = self.bot.interface = Mock()

    def assert_message_sent(self, expected_response: str, to: MeshNode, want_ack: bool = False, multi_response=False):
        if multi_response:
            self.mock_interface.sendText.assert_called()

            # Strip the newline character from the expected response
            expected_response = expected_response.strip()

            # Assert that one of the calls matches the expected
            for call_args in self.mock_interface.sendText.call_args_list:
                if (call_args[1]['destinationId'] == to.user.id
                        and call_args[1]['wantAck'] == want_ack
                        and call_args[1].get('hopLimit') == 5
                        and call_args[0][0].strip() == expected_response):
                    return

            self.fail(
                f"Expected response with destinationId {to.user.id} and wantAck {want_ack}: \n"
                f"{expected_response}\n"
                f"\n"
                f"not found in calls:\n"
                f"{self.mock_interface.sendText.call_args_list}")
        else:
            self.mock_interface.sendText.assert_called_once_with(
                expected_response,
                destinationId=to.user.id,
                wantAck=want_ack,
                hopLimit=5,
            )

    def assert_reaction_sent(self, emoji: str, reply_id: int, channel=0, sender_id: str = None):
        if sender_id:
            self.mock_interface.sendReaction.assert_called_once_with(
                emoji,
                messageId=reply_id,
                destinationId=sender_id
            )
        else:
            self.mock_interface.sendReaction.assert_called_once_with(
                emoji,
                messageId=reply_id,
                channelIndex=channel,
            )
