"""Abstract :class:`RadioInterface` the bot talks to.

Concrete adapters live under their protocol package (e.g.
:mod:`src.meshtastic.radio` for Meshtastic). The bot must never reach past
this interface — anything protocol-specific belongs behind it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from src.radio.events import (
    ConnectionEstablished,
    IncomingPacket,
    IncomingTextMessage,
    NodeUpdate,
)


@dataclass
class RadioHandlers:
    """Callback set the bot registers with a :class:`RadioInterface`.

    Any handler may be ``None``; an adapter must tolerate missing ones.
    All handlers are invoked synchronously inside the radio's receive thread,
    so adapters wrap them with error boundaries (see :mod:`src.radio.errors`).
    """

    on_packet: Optional[Callable[[IncomingPacket], None]] = None
    on_text_message: Optional[Callable[[IncomingTextMessage], None]] = None
    on_node_update: Optional[Callable[[NodeUpdate], None]] = None
    on_connection_established: Optional[Callable[[ConnectionEstablished], None]] = None
    on_disconnected: Optional[Callable[[Optional[Exception]], None]] = None


class RadioInterface(ABC):
    """Protocol-agnostic radio façade.

    Lifecycle: :meth:`set_handlers` → :meth:`connect` → events flow → optionally
    :meth:`disconnect`.
    """

    @abstractmethod
    def set_handlers(self, handlers: RadioHandlers) -> None:
        """Register the callback set the radio invokes for incoming events."""

    @abstractmethod
    def connect(self) -> None:
        """Open the radio connection and start receiving.

        On a successful connection the adapter must invoke
        ``handlers.on_connection_established`` exactly once. Adapters are
        expected to handle their own reconnect/backoff and translate fatal
        failures into ``handlers.on_disconnected`` events; the bot does not
        manage the transport.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Close the radio connection. Idempotent."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """``True`` once a connection has been established and not yet lost."""

    @property
    @abstractmethod
    def local_node_id(self) -> Optional[str]:
        """Local node id in canonical hex form (``!aabbccdd``), or ``None``
        before the connection is established."""

    @property
    @abstractmethod
    def local_nodenum(self) -> Optional[int]:
        """Local node id as an unsigned int, or ``None`` pre-connect."""

    # --- send-side ---------------------------------------------------------

    @abstractmethod
    def send_text(
        self,
        text: str,
        *,
        destination_id: Optional[str] = None,
        channel: int = 0,
        want_ack: bool = False,
        hop_limit: Optional[int] = None,
    ) -> None:
        """Send a text message.

        ``destination_id`` is a canonical hex id for a DM, or ``None`` to
        broadcast on ``channel``.
        """

    @abstractmethod
    def send_reaction(
        self,
        emoji: str,
        message_id: int,
        *,
        destination_id: Optional[str] = None,
        channel: int = 0,
    ) -> None:
        """React to a previously-received message with an emoji."""

    @abstractmethod
    def send_traceroute(
        self,
        target_node_id: int,
        *,
        channel_index: int = 0,
    ) -> None:
        """Send a protocol-appropriate traceroute / route-discovery probe.

        Adapters that don't support traceroute should raise
        :class:`~src.radio.errors.RadioError`.
        """
