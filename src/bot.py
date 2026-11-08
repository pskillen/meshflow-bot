"""Protocol-agnostic bot core.

:class:`MeshflowBot` knows about commands, responders, the node DB, and the
storage API; it does not know about Meshtastic, MeshCore, pubsub, TCP, or
``MeshPacket``. All of that lives behind a :class:`RadioInterface`.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import schedule

from src.api.StorageAPI import StorageAPIWrapper
from src.commands.factory import CommandFactory
from src.data_classes import MeshNode
from src.helpers import pretty_print_last_heard, safe_encode_node_name
from src.packet_log import log_incoming_packet
from src.meshtastic.replay import DEFAULT_MODE, MODE_FLAG, MODE_PASS
from src.meshtastic.self_telemetry import SelfTelemetryThrottle
from src.persistence.commands_logger import AbstractCommandLogger
from src.persistence.node_db import AbstractNodeDB
from src.persistence.node_info import AbstractNodeInfoStore
from src.persistence.packet_dump import dump_packet
from src.persistence.user_prefs import AbstractUserPrefsPersistence
from src.radio.errors import call_safely, get_global_error_counter
from src.radio.events import (
    ConnectionEstablished,
    IdentityChanged,
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
        self.replayed_packets_mode = DEFAULT_MODE
        self.self_telemetry: Optional[SelfTelemetryThrottle] = None

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
                on_identity_changed=self._on_identity_changed,
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

    def on_apply_mc_channel_config(self, channels: list) -> None:
        """Handle apply_mc_channel_config from WebSocket (MeshCore feeders)."""
        from src.meshcore.channel_sync import (
            apply_channels_on_device,
            sync_channels_after_apply,
            sync_channels_to_api,
        )

        if not hasattr(self.radio, "run_coroutine"):
            logger.warning(
                "apply_mc_channel_config ignored: radio does not support MeshCore channel IO"
            )
            return
        if not apply_channels_on_device(self.radio, channels):
            return
        if hasattr(self.radio, "schedule_channel_sync"):
            self.radio.schedule_channel_sync(self.storage_apis, scope_hints=channels)
        elif self.storage_apis:
            sync_channels_after_apply(self.radio, self.storage_apis, channels)
        else:
            for storage_api in self.storage_apis:
                sync_channels_to_api(self.radio, storage_api, scope_hints=channels)

    def on_traceroute_command(self, target_node_id: int) -> None:
        """Handle a traceroute command (e.g. delivered via WebSocket)."""
        if not self.radio.is_connected:
            logger.warning("Traceroute requested but radio not connected; skipping")
            return
        self.radio.send_traceroute(target_node_id)

    def on_refresh_feeder_config(self) -> None:
        """Re-fetch feeder bot-config from API and reschedule periodic flood adverts."""
        if not hasattr(self.radio, "reschedule_flood_advert_from_config"):
            logger.warning(
                "refresh_feeder_config ignored: radio does not support MeshCore config"
            )
            return
        if not self.storage_apis:
            logger.warning("refresh_feeder_config ignored: no storage API configured")
            return
        self.radio.reschedule_flood_advert_from_config(self.storage_apis[0])

    # --- radio event handlers --------------------------------------------

    def _on_connection_established(self, event: ConnectionEstablished) -> None:
        self.init_complete = True
        logger.info(
            "Connected as %s (nodenum=%s)", event.local_node_id, event.local_nodenum
        )
        # Decide v4 vs legacy URLs per destination before the first upload.
        self.probe_feeder_urls()
        for storage_api in self.storage_apis:
            storage_api.report_bot_version()
        if event.extras.get("meshcore") and hasattr(
            self.radio, "schedule_channel_sync"
        ):
            self.radio.schedule_channel_sync(self.storage_apis)
        if event.extras.get("meshcore") and hasattr(
            self.radio, "schedule_flood_advert_from_config"
        ):
            if self.storage_apis:
                self.radio.schedule_flood_advert_from_config(self.storage_apis[0])
        self.print_nodes()
        if self.ws_client:
            self.ws_client.start()

    def probe_feeder_urls(self) -> None:
        """Probe every destination for the v4 feeder URLs (each decides
        separately). Never raises."""
        for storage_api in self.storage_apis:
            try:
                storage_api.probe_feeder_urls()
            except Exception as exc:
                logger.warning("Feeder URL probe failed: %s", exc)

    def _probe_feeder_urls_in_background(self) -> None:
        """Hourly probe on a short-lived thread, so a slow API can't stall the
        scheduler loop."""
        threading.Thread(
            target=self.probe_feeder_urls, name="feeder-url-probe", daemon=True
        ).start()

    def _on_identity_changed(self, event: IdentityChanged) -> None:
        """The radio's reported identity changed (e.g. 2.8 node number): tell
        every API, and resubscribe the WebSocket under the new number."""
        for storage_api in self.storage_apis:
            storage_api.report_bot_version()
        if event.nodenum_changed and self.ws_client:
            self.ws_client.reconnect()

    def _on_disconnected(self, error: Optional[Exception]) -> None:
        self.init_complete = False
        if error:
            logger.warning("Radio disconnected: %s", error)

    def _on_packet(self, event: IncomingPacket) -> None:
        log_incoming_packet(event)
        # REPLAYED_PACKETS=pass behaves as if nothing was classified.
        replayed = event.replayed and self.replayed_packets_mode != MODE_PASS
        if event.raw is not None:
            if isinstance(event.raw, dict) and event.raw.get("meshcore"):
                pass  # MeshCore JSON dumps live under data/meshcore_packets/ (see MeshCoreRadio)
            elif isinstance(event.raw, dict) and "decoded" in event.raw:
                dump_packet(
                    event.raw,
                    feeder_num=getattr(self.radio, "local_nodenum", None),
                    feeder_fw=getattr(self.radio, "firmware_version", None),
                    replayed=replayed,
                )

        if replayed and self.replayed_packets_mode != MODE_FLAG:
            return  # drop: not uploaded, not counted as live activity

        if self.ignore_portnums and event.portnum in self.ignore_portnums:
            logger.info(
                "Skipping API submission for packet with portnum %s (in IGNORE_PORTNUMS)",
                event.portnum,
            )
        elif not event.has_decoded:
            pass  # encrypted-only packet; nothing to upload
        elif event.self_telemetry_variant:
            # Meshtastic self telemetry: keep the newest sample per variant;
            # the scheduler uploads it once per interval (0 = disabled).
            if self.self_telemetry is not None and isinstance(event.raw, dict):
                self.self_telemetry.record(event.self_telemetry_variant, event.raw)
        elif event.is_self_telemetry:
            pass  # MeshCore self telemetry; not uploaded
        else:
            raw = event.raw if event.raw is not None else event
            if replayed:
                raw = self._flag_replayed(raw)
            self._upload_raw(raw)

        sender = event.from_id
        if not sender or replayed:  # a replay is not live activity
            return

        node = self.node_db.get_by_radio_id(sender)
        if not node:
            return

        # Track activity, except for self-telemetry which would inflate counts
        if not (sender == self.my_id and event.portnum == "TELEMETRY_APP"):
            self.node_info.node_packet_received(sender, event.portnum)

        if sender == self.my_id and event.to_id is not None:
            recipient = self.node_db.get_by_radio_id(event.to_id)
            recipient_name = recipient.long_name if recipient else event.to_id
            logger.debug(
                "Received packet from self: %s (port %s)", recipient_name, event.portnum
            )

    @staticmethod
    def _flag_replayed(raw):
        """Copy of the packet dict with ``"replayed": true`` for the ingest body."""
        return {**raw, "replayed": True} if isinstance(raw, dict) else raw

    def _upload_raw(self, raw) -> None:
        for storage_api in self.storage_apis:
            if isinstance(raw, dict) and raw.get("meshcore"):
                call_safely(
                    "bot.store_raw_meshcore_packet",
                    storage_api.store_raw_meshcore_packet,
                    raw,
                    counter=self._error_counter,
                )
            else:
                call_safely(
                    "bot.store_raw_packet",
                    storage_api.store_raw_packet,
                    raw,
                    counter=self._error_counter,
                )

    def upload_self_telemetry(self) -> None:
        """Scheduled job: upload the newest unsent self-telemetry sample per variant."""
        if self.self_telemetry is None:
            return
        for packet in self.self_telemetry.flush():
            self._upload_raw(packet)

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
            logger.info(
                "New user: %s (last heard %s)", node.user.long_name, last_heard_str
            )

    # --- private message dispatch ----------------------------------------

    def _handle_private_message(self, message: IncomingTextMessage) -> None:
        sender = self.node_db.get_by_radio_id(message.from_id)
        sender_name = sender.long_name if sender else message.from_id
        logger.info("Received private message: '%s' from %s", message.text, sender_name)

        words = message.text.split()
        if not words:
            return
        command_name = words[0]
        command_instance = CommandFactory.create_command(command_name, self)
        if command_instance:
            self.command_logger.log_command(
                message.from_id, command_instance, message.text
            )
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
            sender = self.node_db.get_by_radio_id(message.from_id)
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
            node = self.node_db.get_by_radio_id(node_id)
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
        if self.storage_apis:
            schedule.every(1).hours.do(self._probe_feeder_urls_in_background)
        if self.self_telemetry is not None and self.self_telemetry.enabled:
            schedule.every(self.self_telemetry.interval_seconds).seconds.do(
                self.upload_self_telemetry
            )
        while True:
            schedule.run_pending()
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                return


# Backward-compatible alias so anything importing the old name keeps working
# during the migration period. New code should import :class:`MeshflowBot`.
MeshtasticBot = MeshflowBot
