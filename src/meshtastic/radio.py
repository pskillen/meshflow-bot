"""Meshtastic implementation of :class:`~src.radio.interface.RadioInterface`.

Owns the underlying :class:`AutoReconnectTcpInterface`, subscribes to the
Meshtastic library's pubsub topics, and translates each packet into the
bot's protocol-agnostic events. The bot itself never imports from
``meshtastic.*`` or talks to ``pub`` — that all happens here.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional

from meshtastic import BROADCAST_ADDR
from pubsub import pub

from src.meshtastic.tcp_interface import (
    AutoReconnectTcpInterface,
    SupportsMessageReactionInterface,
)
from src.meshtastic.traceroute import send_traceroute as _send_traceroute
from src.meshtastic.translation import (
    nodenum_to_id,
    packet_to_incoming,
    packet_to_text_message,
    node_dict_to_node_update,
)
from src.meshtastic.identity import (
    FeederIdentity,
    read_firmware_version,
    read_identity,
    read_node_num,
)
from src.persistence.packet_dump import dump_nodes
from src.radio.errors import RadioError, call_safely, get_global_error_counter
from src.radio.events import ConnectionEstablished, IdentityChanged
from src.radio.interface import RadioHandlers, RadioInterface

logger = logging.getLogger(__name__)

IDENTITY_CHECK_INTERVAL_SECONDS = 60.0


class MeshtasticRadio(RadioInterface):
    """RadioInterface backed by the Meshtastic Python library over TCP."""

    def __init__(self, hostname: str):
        self._hostname = hostname
        self._handlers = RadioHandlers()
        self._interface: Optional[SupportsMessageReactionInterface] = None
        self._is_connected = False
        self._local_nodenum: Optional[int] = None
        self._local_id: Optional[str] = None
        self._reconnect_lock = threading.Lock()
        self._error_counter = get_global_error_counter()
        self._pubsub_subscribed = False
        self._identity = FeederIdentity()
        self._identity_lock = threading.Lock()
        self._identity_timer: Optional[threading.Timer] = None

    # --- RadioInterface ---------------------------------------------------

    def set_handlers(self, handlers: RadioHandlers) -> None:
        self._handlers = handlers

    def connect(self) -> None:
        logger.info("MeshtasticRadio: connecting to %s...", self._hostname)
        self._is_connected = False

        self._ensure_pubsub_subscribed()

        old_packet_queue = (
            self._interface.packet_queue
            if self._interface and hasattr(self._interface, "packet_queue")
            else None
        )

        self._interface = AutoReconnectTcpInterface(
            hostname=self._hostname,
            error_handler=self._on_transport_error,
            packet_queue=old_packet_queue,
        )

        logger.info(
            "MeshtasticRadio: TCP interface created; awaiting library connect event"
        )

    def disconnect(self) -> None:
        self._is_connected = False
        self._stop_identity_timer()
        if not self._interface:
            return
        try:
            self._interface.close()
            self._interface._disconnected()
        except OSError as exc:
            logger.warning("MeshtasticRadio: close failed: %s", exc)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def local_node_id(self) -> Optional[str]:
        return self._local_id

    @property
    def local_nodenum(self) -> Optional[int]:
        return self._local_nodenum

    @property
    def firmware_version(self) -> Optional[str]:
        """Feeder firmware version if the library exposes it, else ``None``."""
        return read_firmware_version(self._interface)

    @property
    def identity(self) -> FeederIdentity:
        """What the bot currently reports about the local radio (key, MAC,
        node number, firmware, region, preset). Fields the radio does not
        report are ``None``."""
        return self._identity

    def send_text(
        self,
        text: str,
        *,
        destination_id: Optional[str] = None,
        channel: int = 0,
        want_ack: bool = False,
        hop_limit: Optional[int] = None,
    ) -> None:
        self._require_interface()
        kwargs = {"channelIndex": channel, "wantAck": want_ack}
        if destination_id is not None:
            kwargs["destinationId"] = destination_id
        if hop_limit is not None:
            kwargs["hopLimit"] = hop_limit
        logger.debug(
            "MeshtasticRadio: send_text dest=%s ch=%s", destination_id, channel
        )
        self._interface.sendText(text, **kwargs)

    def send_reaction(
        self,
        emoji: str,
        message_id: int,
        *,
        destination_id: Optional[str] = None,
        channel: int = 0,
    ) -> None:
        self._require_interface()
        kwargs = {"messageId": message_id}
        if destination_id is not None:
            kwargs["destinationId"] = destination_id
        else:
            kwargs["channelIndex"] = channel
        self._interface.sendReaction(emoji, **kwargs)

    def send_traceroute(
        self,
        target_node_id: int,
        *,
        channel_index: int = 0,
    ) -> None:
        if not self._interface or not self._is_connected:
            logger.warning(
                "MeshtasticRadio: send_traceroute called before connect; skipping"
            )
            return
        _send_traceroute(self._interface, target_node_id, channel_index=channel_index)

    # --- pubsub plumbing --------------------------------------------------

    def _ensure_pubsub_subscribed(self) -> None:
        if self._pubsub_subscribed:
            return
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_receive_text, "meshtastic.receive.text")
        pub.subscribe(self._on_node_updated, "meshtastic.node.updated")
        pub.subscribe(
            self._on_connection_established, "meshtastic.connection.established"
        )
        self._pubsub_subscribed = True

    def _require_interface(self) -> None:
        if self._interface is None:
            raise RadioError("MeshtasticRadio: not connected")

    def _on_connection_established(self, interface, topic=pub.AUTO_TOPIC):
        previous_nodenum = self._local_nodenum
        self._local_nodenum = interface.localNode.nodeNum
        self._local_id = nodenum_to_id(self._local_nodenum)
        self._is_connected = True
        with self._identity_lock:
            self._identity = read_identity(interface)
        logger.info("MeshtasticRadio: connection established (%s)", self._local_id)
        if previous_nodenum is not None and previous_nodenum != self._local_nodenum:
            self._log_nodenum_change(previous_nodenum, self._local_nodenum)
            self._emit_identity_changed(previous_nodenum, self._local_nodenum)
        self._start_identity_timer()
        call_safely(
            "radio.dump_nodes",
            dump_nodes,
            getattr(interface, "nodes", None),
            counter=self._error_counter,
        )

        if self._handlers.on_connection_established:
            call_safely(
                "radio.on_connection_established",
                self._handlers.on_connection_established,
                ConnectionEstablished(
                    local_node_id=self._local_id,
                    local_nodenum=self._local_nodenum,
                ),
                counter=self._error_counter,
            )

    def _on_receive(self, packet, interface):
        event = packet_to_incoming(packet, local_node_id=self._local_id)
        if self._handlers.on_packet:
            call_safely(
                "radio.on_packet",
                self._handlers.on_packet,
                event,
                counter=self._error_counter,
            )

    def _on_receive_text(self, packet, interface):
        msg = packet_to_text_message(packet, local_node_id=self._local_id)
        if self._handlers.on_text_message:
            call_safely(
                "radio.on_text_message",
                self._handlers.on_text_message,
                msg,
                counter=self._error_counter,
            )

    def _on_node_updated(self, node, interface):
        # Some library callbacks run before we've seen the connection event.
        if self._local_nodenum is None and getattr(interface, "localNode", None):
            self._local_nodenum = interface.localNode.nodeNum
            self._local_id = nodenum_to_id(self._local_nodenum)
        if isinstance(node, dict) and node.get("num") in (
            self._local_nodenum,
            read_node_num(interface),
        ):
            self.check_identity()
        update = node_dict_to_node_update(node)
        if update is None:
            return
        if self._handlers.on_node_update:
            call_safely(
                "radio.on_node_update",
                self._handlers.on_node_update,
                update,
                counter=self._error_counter,
            )

    # --- identity ---------------------------------------------------------

    def check_identity(self) -> bool:
        """Re-read the local radio's identity; report a change to the bot.

        Called on local ``node.updated`` events and every
        ``IDENTITY_CHECK_INTERVAL_SECONDS``. In 2.8 the node number is
        ``crc32(public key)``, so it can change mid-session (a key minted
        after the region is set). On a node-number change this logs WARNING;
        on any change it refreshes :attr:`identity` and calls
        ``handlers.on_identity_changed`` so the bot re-reports and
        resubscribes the WebSocket under the new number. Returns ``True`` if
        something changed."""
        interface = self._interface
        if interface is None or not self._is_connected:
            return False
        try:
            current = read_identity(interface)
        except Exception as exc:  # read_identity should not raise; be safe
            logger.debug("MeshtasticRadio: identity read failed: %s", exc)
            return False
        with self._identity_lock:
            old_nodenum = self._local_nodenum
            new_nodenum = current.node_num or old_nodenum
            if current == self._identity and new_nodenum == old_nodenum:
                return False
            self._identity = current
            if new_nodenum != old_nodenum:
                self._local_nodenum = new_nodenum
                self._local_id = nodenum_to_id(new_nodenum)
        if new_nodenum != old_nodenum:
            self._log_nodenum_change(old_nodenum, new_nodenum)
        else:
            logger.info("MeshtasticRadio: reported identity changed; refreshing")
        self._emit_identity_changed(old_nodenum, new_nodenum)
        return True

    def _log_nodenum_change(self, old: Optional[int], new: Optional[int]) -> None:
        logger.warning(
            "MeshtasticRadio: local node number changed from %s to %s "
            "(Meshtastic 2.8 derives it from the public key); "
            "refreshing reported identity and reconnecting the WebSocket",
            old,
            new,
        )

    def _emit_identity_changed(self, old: Optional[int], new: Optional[int]) -> None:
        if self._handlers.on_identity_changed:
            call_safely(
                "radio.on_identity_changed",
                self._handlers.on_identity_changed,
                IdentityChanged(old_nodenum=old, new_nodenum=new),
                counter=self._error_counter,
            )

    def _start_identity_timer(self) -> None:
        self._stop_identity_timer()
        timer = threading.Timer(IDENTITY_CHECK_INTERVAL_SECONDS, self._identity_tick)
        timer.daemon = True
        self._identity_timer = timer
        timer.start()

    def _stop_identity_timer(self) -> None:
        timer, self._identity_timer = self._identity_timer, None
        if timer is not None:
            timer.cancel()

    def _identity_tick(self) -> None:
        try:
            self.check_identity()
        finally:
            if self._is_connected:
                self._start_identity_timer()

    # --- transport error handling ----------------------------------------

    def _on_transport_error(self, error: Optional[Exception]) -> None:
        """Called by AutoReconnectTcpInterface when the TCP transport dies.

        Surfaces the failure to the bot via ``handlers.on_disconnected`` and
        runs an in-process exponential backoff reconnect loop. Mirrors what
        the previous bot.py did, except the loop is owned by the adapter."""
        with self._reconnect_lock:
            self._is_connected = False
            self._error_counter.increment("radio.transport_error")
            logger.error("MeshtasticRadio: transport error: %s", error)

            if self._handlers.on_disconnected:
                call_safely(
                    "radio.on_disconnected",
                    self._handlers.on_disconnected,
                    error,
                    counter=self._error_counter,
                )

            self.disconnect()

            backoff = 5.0
            max_backoff = 300.0
            while True:
                try:
                    self.connect()
                    logger.info("MeshtasticRadio: reconnected")
                    return
                except Exception as exc:
                    logger.error("MeshtasticRadio: reconnect attempt failed: %s", exc)
                    if backoff >= max_backoff:
                        logger.error("MeshtasticRadio: max backoff reached, exiting")
                        sys.exit(1)
                    backoff = min(backoff * 1.5, max_backoff)
                    logger.info("MeshtasticRadio: next reconnect in %.0fs", backoff)
                    time.sleep(backoff)
