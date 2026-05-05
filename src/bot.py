"""Protocol-agnostic bot core.

:class:`MeshflowBot` knows about commands, responders, the node DB, and the
storage API; it does not know about Meshtastic, MeshCore, pubsub, TCP, or
``MeshPacket``. All of that lives behind a :class:`RadioInterface`.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import schedule

from src.api.StorageAPI import StorageAPIWrapper
from src.commands.factory import CommandFactory
from src.data_classes import MeshNode
from src.helpers import pretty_print_last_heard, safe_encode_node_name
from src.persistence.commands_logger import AbstractCommandLogger
from src.persistence.node_db import AbstractNodeDB
from src.persistence.node_info import AbstractNodeInfoStore
from src.persistence.packet_dump import dump_packet
from src.persistence.user_prefs import AbstractUserPrefsPersistence
from src.radio.errors import call_safely, get_global_error_counter
from src.radio.events import (
    ConnectionEstablished,
    IncomingPacket,
    IncomingTextMessage,
    NodeUpdate,
)
from src.radio.interface import RadioHandlers, RadioInterface
from src.responders.responder_factory import ResponderFactory

logger = logging.getLogger(__name__)


class MeshflowBot:
    admin_nodes: list[str]
    ignore_portnums: frozenset

    radio: RadioInterface
    init_complete: bool

    node_db: AbstractNodeDB
    node_info: AbstractNodeInfoStore
    command_logger: AbstractCommandLogger
    user_prefs_persistence: AbstractUserPrefsPersistence

    storage_apis: list[StorageAPIWrapper]
    ws_client: object | None  # MeshflowWSClient when configured

    def __init__(self, radio: RadioInterface):
        self.radio = radio
        self.admin_nodes = []
        self.ignore_portnums = frozenset()

        self.init_complete = False

        self.node_db = None
        self.node_info = None
        self.command_logger = None
        self.user_prefs_persistence = None
        self.storage_apis = []
        self.ws_client = None

        self._error_counter = get_global_error_counter()

        radio.set_handlers(
            RadioHandlers(
                on_packet=self._on_packet,
                on_text_message=self._on_text_message,
                on_node_update=self._on_node_update,
                on_connection_established=self._on_connection_established,
                on_disconnected=self._on_disconnected,
            )
        )

    # --- connection-derived state ----------------------------------------

    @property
    def my_id(self) -> Optional[str]:
        return self.radio.local_node_id

    @property
    def my_nodenum(self) -> Optional[int]:
        return self.radio.local_nodenum

    # --- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        self.radio.connect()

    def disconnect(self) -> None:
        self.radio.disconnect()

    def on_traceroute_command(self, target_node_id: int) -> None:
        """Handle a traceroute command (e.g. delivered via WebSocket)."""
        if not self.radio.is_connected:
            logger.warning("Traceroute requested but radio not connected; skipping")
            return
        self.radio.send_traceroute(target_node_id)

    # --- radio event handlers --------------------------------------------

    def _on_connection_established(self, event: ConnectionEstablished) -> None:
        self.init_complete = True
        logger.info("Connected as %s (nodenum=%s)", event.local_node_id, event.local_nodenum)
        self.print_nodes()
        if self.ws_client:
            self.ws_client.start()

    def _on_disconnected(self, error: Optional[Exception]) -> None:
        self.init_complete = False
        if error:
            logger.warning("Radio disconnected: %s", error)

    def _on_packet(self, event: IncomingPacket) -> None:
        if event.raw is not None:
            dump_packet(event.raw)

        if self.ignore_portnums and event.portnum in self.ignore_portnums:
            logger.info(
                "Skipping API submission for packet with portnum %s (in IGNORE_PORTNUMS)",
                event.portnum,
            )
        elif not event.has_decoded:
            pass  # encrypted-only packet; nothing to upload
        elif event.is_self_telemetry:
            pass  # self device-metrics; another bot will capture over the air
        else:
            for storage_api in self.storage_apis:
                call_safely(
                    "bot.store_raw_packet",
                    storage_api.store_raw_packet,
                    event.raw if event.raw is not None else event,
                    counter=self._error_counter,
                )

        sender = event.from_id
        if not sender:
            return

        node = self.node_db.get_by_id(sender)
        if not node:
            return

        # Track activity, except for self-telemetry which would inflate counts
        if not (sender == self.my_id and event.portnum == "TELEMETRY_APP"):
            self.node_info.node_packet_received(sender, event.portnum)

        if sender == self.my_id and event.to_id is not None:
            recipient = self.node_db.get_by_id(event.to_id)
            recipient_name = recipient.long_name if recipient else event.to_id
            logger.debug(
                "Received packet from self: %s (port %s)", recipient_name, event.portnum
            )

    def _on_text_message(self, message: IncomingTextMessage) -> None:
        if message.is_dm:
            self._handle_private_message(message)
        else:
            self._handle_public_message(message)

    def _on_node_update(self, update: NodeUpdate) -> None:
        node = update.node
        self.node_db.store_node(node)
        self.node_info.update_last_heard(node.user.id, update.last_heard)

        for storage_api in self.storage_apis:
            call_safely(
                "bot.store_node",
                storage_api.store_node,
                node,
                counter=self._error_counter,
            )

        if self.init_complete:
            last_heard_str = pretty_print_last_heard(update.last_heard)
            logger.info("New user: %s (last heard %s)", node.user.long_name, last_heard_str)

    # --- private message dispatch ----------------------------------------

    def _handle_private_message(self, message: IncomingTextMessage) -> None:
        sender = self.node_db.get_by_id(message.from_id)
        sender_name = sender.long_name if sender else message.from_id
        logger.info("Received private message: '%s' from %s", message.text, sender_name)

        words = message.text.split()
        if not words:
            return
        command_name = words[0]
        command_instance = CommandFactory.create_command(command_name, self)
        if command_instance:
            self.command_logger.log_command(message.from_id, command_instance, message.text)
            call_safely(
                "bot.handle_command",
                command_instance.handle_packet,
                message,
                counter=self._error_counter,
            )
        else:
            self.command_logger.log_unknown_request(message.from_id, message.text)

    def _handle_public_message(self, message: IncomingTextMessage) -> None:
        responder = ResponderFactory.match_responder(message.text, self)
        if responder is None:
            return

        outcome = call_safely(
            "bot.handle_responder",
            responder.handle_packet,
            message,
            counter=self._error_counter,
        )
        if outcome:
            sender = self.node_db.get_by_id(message.from_id)
            sender_name = sender.long_name if sender else message.from_id
            logger.info(
                "Handled message from %s with responder %s: %s",
                sender_name,
                responder.__class__.__name__,
                message.text,
            )
            self.command_logger.log_responder_handled(
                message.from_id, responder, message.text
            )

    # --- introspection / scheduler ---------------------------------------

    def print_nodes(self) -> None:
        online_nodes = self.node_info.get_online_nodes()
        offline_nodes = self.node_info.get_offline_nodes()
        logger.info("Online nodes: (%s)", len(online_nodes))
        sorted_nodes = sorted(online_nodes, key=lambda x: online_nodes[x], reverse=True)
        for node_id in sorted_nodes:
            if node_id == self.my_id:
                continue
            node = self.node_db.get_by_id(node_id)
            last_heard = self.node_info.get_last_heard(node_id)
            last_heard_str = pretty_print_last_heard(last_heard)
            encoded_name = safe_encode_node_name(node.long_name) if node else node_id
            logger.info("- %s (last heard %s)", encoded_name, last_heard_str)
        logger.info("- Plus %s offline nodes", len(offline_nodes))

    def get_global_context(self) -> dict:
        return {
            "nodes": self.node_db.list_nodes(),
            "online_nodes": self.node_info.get_online_nodes(),
            "offline_nodes": self.node_info.get_offline_nodes(),
        }

    def get_node_by_short_name(self, short_name: str) -> MeshNode.User | None:
        for node in self.node_db.list_nodes():
            if node.short_name.lower() == short_name.lower():
                return node
        return None

    def metrics(self) -> dict[str, int]:
        """Snapshot of in-process error counters. Useful for admin diagnostics."""
        return self._error_counter.snapshot()

    def start_scheduler(self) -> None:
        schedule.every().day.at("00:00").do(self.node_info.reset_packets_today)
        while True:
            schedule.run_pending()
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                return


# Backward-compatible alias so anything importing the old name keeps working
# during the migration period. New code should import :class:`MeshflowBot`.
MeshtasticBot = MeshflowBot
