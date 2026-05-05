"""In-memory :class:`RadioInterface` for tests.

Records every send and lets a test inject events via the public
``deliver_*`` methods. Send methods are :class:`unittest.mock.MagicMock`
so existing ``assert_called_with`` assertions keep working.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

from src.radio.events import (
    ConnectionEstablished,
    IncomingPacket,
    IncomingTextMessage,
    NodeUpdate,
)
from src.radio.interface import RadioHandlers, RadioInterface


class FakeRadio(RadioInterface):
    # Stub the abstract methods so the ABC is satisfied at class-definition
    # time. ``__init__`` then overrides them on the instance with MagicMocks
    # so tests can use ``assert_called_with`` etc.
    def connect(self) -> None:  # pragma: no cover - overridden in __init__
        pass

    def disconnect(self) -> None:  # pragma: no cover
        pass

    def send_text(self, *args, **kwargs) -> None:  # pragma: no cover
        pass

    def send_reaction(self, *args, **kwargs) -> None:  # pragma: no cover
        pass

    def send_traceroute(self, *args, **kwargs) -> None:  # pragma: no cover
        pass

    def __init__(
        self, *, local_node_id: Optional[str] = None, local_nodenum: Optional[int] = None
    ):
        self._local_node_id = local_node_id
        self._local_nodenum = local_nodenum
        self._is_connected = False
        self._handlers = RadioHandlers()

        # Send sites are MagicMocks so tests can assert on calls naturally
        self.send_text = MagicMock(name="send_text")
        self.send_reaction = MagicMock(name="send_reaction")
        self.send_traceroute = MagicMock(name="send_traceroute")
        self.connect = MagicMock(name="connect", side_effect=self._mark_connected)
        self.disconnect = MagicMock(
            name="disconnect", side_effect=self._mark_disconnected
        )

    def _mark_connected(self):
        self._is_connected = True

    def _mark_disconnected(self):
        self._is_connected = False

    # --- RadioInterface plumbing -----------------------------------------

    def set_handlers(self, handlers: RadioHandlers) -> None:
        self._handlers = handlers

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def local_node_id(self) -> Optional[str]:
        return self._local_node_id

    @property
    def local_nodenum(self) -> Optional[int]:
        return self._local_nodenum

    # --- test helpers: deliver events as if they came off the air --------

    def set_local_node(self, node_id: str, nodenum: int = 0) -> None:
        self._local_node_id = node_id
        self._local_nodenum = nodenum

    def deliver_connection_established(self) -> None:
        self._is_connected = True
        if self._handlers.on_connection_established:
            self._handlers.on_connection_established(
                ConnectionEstablished(
                    local_node_id=self._local_node_id or "",
                    local_nodenum=self._local_nodenum or 0,
                )
            )

    def deliver_disconnected(self, error: Optional[Exception] = None) -> None:
        self._is_connected = False
        if self._handlers.on_disconnected:
            self._handlers.on_disconnected(error)

    def deliver_packet(self, event: IncomingPacket) -> None:
        if self._handlers.on_packet:
            self._handlers.on_packet(event)

    def deliver_text_message(self, message: IncomingTextMessage) -> None:
        if self._handlers.on_text_message:
            self._handlers.on_text_message(message)

    def deliver_node_update(self, update: NodeUpdate) -> None:
        if self._handlers.on_node_update:
            self._handlers.on_node_update(update)
