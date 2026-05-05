import unittest
from abc import ABC

from src.bot import MeshflowBot
from src.data_classes import MeshNode
from test.fake_radio import FakeRadio
from test.test_setup_data import get_test_bot


class BaseFeatureTestCase(unittest.TestCase, ABC):
    bot: MeshflowBot
    fake_radio: FakeRadio
    test_admin_nodes: list[MeshNode] = []
    test_non_admin_nodes: list[MeshNode] = []
    test_nodes: list[MeshNode] = []

    def setUp(self):
        self.bot, self.test_non_admin_nodes, self.test_admin_nodes = get_test_bot()
        self.test_nodes = self.test_non_admin_nodes + self.test_admin_nodes
        self.fake_radio = self.bot.radio  # type: ignore[assignment]
        # Backward-compat alias: many tests historically read bot.interface
        self.mock_interface = _SendCallShim(self.fake_radio)

    def assert_message_sent(
        self,
        expected_response: str,
        to: MeshNode,
        want_ack: bool = False,
        multi_response: bool = False,
    ):
        if multi_response:
            self.fake_radio.send_text.assert_called()
            expected_response = expected_response.strip()
            for call_args in self.fake_radio.send_text.call_args_list:
                if (
                    call_args.kwargs.get("destination_id") == to.user.id
                    and call_args.kwargs.get("want_ack") == want_ack
                    and call_args.kwargs.get("hop_limit") == 5
                    and call_args.args[0].strip() == expected_response
                ):
                    return
            self.fail(
                f"Expected response with destination_id {to.user.id} and want_ack {want_ack}: \n"
                f"{expected_response}\n"
                f"\nnot found in calls:\n{self.fake_radio.send_text.call_args_list}"
            )
        else:
            self.fake_radio.send_text.assert_called_once_with(
                expected_response,
                destination_id=to.user.id,
                want_ack=want_ack,
                hop_limit=5,
            )

    def assert_reaction_sent(
        self,
        emoji: str,
        reply_id: int,
        channel: int = 0,
        sender_id: str | None = None,
    ):
        if sender_id:
            self.fake_radio.send_reaction.assert_called_once_with(
                emoji, reply_id, destination_id=sender_id
            )
        else:
            self.fake_radio.send_reaction.assert_called_once_with(
                emoji, reply_id, channel=channel
            )


class _SendCallShim:
    """Compat shim so legacy tests reading ``self.bot.interface.sendText`` /
    ``sendReaction`` still find a Mock with a sensible call list.

    New tests should read ``self.fake_radio.send_text`` etc. directly.
    """

    def __init__(self, fake_radio: FakeRadio):
        self.sendText = fake_radio.send_text
        self.sendReaction = fake_radio.send_reaction
