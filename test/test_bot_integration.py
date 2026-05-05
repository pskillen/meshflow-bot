"""Integration-style tests for :class:`MeshflowBot` driven through a
:class:`FakeRadio` — exercises the event path end-to-end without mocking the
radio interface itself."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import unittest

from src.bot import MeshflowBot
from src.data_classes import MeshNode
from src.persistence.node_db import InMemoryNodeDB
from src.persistence.node_info import InMemoryNodeInfoStore
from src.radio.events import (
    ConnectionEstablished,
    IncomingPacket,
    IncomingTextMessage,
    NodeUpdate,
)
from test.fake_radio import FakeRadio


def _build_bot():
    radio = FakeRadio(local_node_id="!aabbccdd", local_nodenum=0xaabbccdd)
    bot = MeshflowBot(radio=radio)
    bot.node_db = InMemoryNodeDB()
    bot.node_info = InMemoryNodeInfoStore()
    bot.command_logger = MagicMock()
    bot.user_prefs_persistence = MagicMock()
    return bot, radio


class TestMeshflowBotEventRouting(unittest.TestCase):
    def test_connection_marks_init_complete(self):
        bot, radio = _build_bot()
        bot.print_nodes = MagicMock()  # avoid log spam

        radio.deliver_connection_established()

        self.assertTrue(bot.init_complete)
        bot.print_nodes.assert_called_once()

    def test_incoming_packet_increments_node_info(self):
        bot, radio = _build_bot()

        node = MeshNode()
        node.user = MeshNode.User(node_id="!11112222", long_name="Alice")
        bot.node_db.store_node(node)

        radio.deliver_packet(
            IncomingPacket(
                portnum="POSITION_APP",
                from_id="!11112222",
                to_id="!aabbccdd",
                has_decoded=True,
            )
        )

        self.assertEqual(bot.node_info.get_node_packets_today("!11112222"), 1)

    def test_node_update_stores_node_and_uploads(self):
        bot, radio = _build_bot()
        storage = MagicMock()
        bot.storage_apis = [storage]

        node = MeshNode()
        node.user = MeshNode.User(node_id="!11112222", long_name="Alice")
        radio.deliver_node_update(NodeUpdate(node=node, last_heard=datetime.now(timezone.utc)))

        self.assertIsNotNone(bot.node_db.get_by_id("!11112222"))
        storage.store_node.assert_called_once_with(node)

    def test_text_message_dm_triggers_command(self):
        bot, radio = _build_bot()
        # Sender must exist in node_db for the bot to log them
        sender = MeshNode()
        sender.user = MeshNode.User(node_id="!11112222", long_name="Alice")
        bot.node_db.store_node(sender)

        radio.deliver_text_message(
            IncomingTextMessage(
                text="!ping",
                from_id="!11112222",
                to_id="!aabbccdd",
                channel=0,
                message_id=1,
                is_dm=True,
            )
        )

        # !ping reacts via send_reaction, then sends a !pong reply
        self.assertTrue(radio.send_text.called)
        radio.send_reaction.assert_called()

    def test_command_handler_exception_does_not_kill_bot(self):
        bot, radio = _build_bot()
        # A command body that raises must not propagate. Use a sender that
        # exists in node_db so the bot makes it past the early lookup.
        sender = MeshNode()
        sender.user = MeshNode.User(node_id="!11112222", long_name="Alice")
        bot.node_db.store_node(sender)

        # Inject a synthetic command that explodes
        from src.commands.factory import CommandFactory

        class _Boom:
            def __init__(self, _bot):
                pass

            def get_command_for_logging(self, _msg):
                return ("boom", None, None)

            def handle_packet(self, _msg):
                raise RuntimeError("boom!")

        original = CommandFactory.commands.get("!boom")
        CommandFactory.commands["!boom"] = {
            "class": __name__ + "._Boom",
            "args": [],
        }
        # Make the dynamic import resolve to our local class
        import sys

        sys.modules[__name__]._Boom = _Boom

        try:
            radio.deliver_text_message(
                IncomingTextMessage(
                    text="!boom",
                    from_id="!11112222",
                    to_id="!aabbccdd",
                    is_dm=True,
                )
            )
        finally:
            if original is None:
                CommandFactory.commands.pop("!boom", None)
            else:
                CommandFactory.commands["!boom"] = original

        # Bot survived; counter incremented
        snapshot = bot.metrics()
        self.assertGreaterEqual(snapshot.get("bot.handle_command", 0), 1)


if __name__ == "__main__":
    unittest.main()
