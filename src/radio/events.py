"""Protocol-agnostic events emitted by a :class:`RadioInterface`.

These dataclasses are the only shape the bot, commands, and responders ever
see. Each concrete radio adapter is responsible for translating its protocol
into these events.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.data_classes import MeshNode


@dataclass
class IncomingPacket:
    """A packet received from the radio, in protocol-agnostic form."""

    portnum: str
    """Portnum / message-type as an upper-case string (e.g. ``TEXT_MESSAGE_APP``)."""

    from_id: Optional[str]
    """Sender node id in canonical hex form (``!aabbccdd``) or ``None`` if unknown."""

    to_id: Optional[str]
    """Destination node id, or ``None`` for unaddressed broadcasts."""

    channel: int = 0

    has_decoded: bool = False
    """``True`` if the packet had a decoded payload (i.e. not still encrypted)."""

    is_self_telemetry: bool = False
    """``True`` for device-metrics telemetry packets sourced from the local node.
    The bot uses this to skip uploading duplicates, since another bot will
    capture the same packet over the air."""

    raw: Any = None
    """The protocol-native packet (e.g. a Meshtastic ``MeshPacket`` dict).
    Only the storage uploader and the originating adapter should look at this."""


@dataclass
class IncomingTextMessage:
    """A decoded text message routed to commands/responders.

    Field names are the protocol-agnostic ones the bot uses; an adapter is
    expected to populate them from its native packet shape.
    """

    text: str
    from_id: str
    to_id: str
    channel: int = 0
    message_id: int = 0
    hop_start: int = 0
    hop_limit: int = 0
    is_dm: bool = False
    raw: Any = None
    """The protocol-native packet that produced this message, kept opaque
    for adapters that need it (e.g. for traceroute correlation)."""

    @property
    def hops_away(self) -> int:
        """Hops travelled to reach us (``hop_start - hop_limit``)."""
        return self.hop_start - self.hop_limit


@dataclass
class NodeUpdate:
    """A node's user/position/metrics changed."""

    node: MeshNode
    last_heard: datetime
    raw: Any = None


@dataclass
class ConnectionEstablished:
    """The radio is connected and ready to send/receive."""

    local_node_id: str
    """Local node id in canonical hex form (``!aabbccdd``)."""

    local_nodenum: int
    """Local node id as an unsigned int."""

    extras: dict = field(default_factory=dict)
    """Adapter-specific connection details (e.g. firmware version) — opaque
    to the bot."""
