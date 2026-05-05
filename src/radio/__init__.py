"""Protocol-agnostic radio abstraction.

The bot interacts with a radio only through :class:`RadioInterface` and the
typed events in :mod:`src.radio.events`. Concrete radios (e.g.
:class:`src.meshtastic.radio.MeshtasticRadio`) live under their own protocol
package and translate that protocol's wire format into these events.
"""

from src.radio.errors import RadioError, safe_callback
from src.radio.events import (
    ConnectionEstablished,
    IncomingPacket,
    IncomingTextMessage,
    NodeUpdate,
)
from src.radio.interface import RadioHandlers, RadioInterface

__all__ = [
    "ConnectionEstablished",
    "IncomingPacket",
    "IncomingTextMessage",
    "NodeUpdate",
    "RadioError",
    "RadioHandlers",
    "RadioInterface",
    "safe_callback",
]
