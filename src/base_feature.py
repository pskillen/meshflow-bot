"""Shared messaging helpers for commands and responders.

Routes through :attr:`MeshflowBot.radio` (a :class:`RadioInterface`) so
nothing in the command/responder layer ever touches a Meshtastic-specific
type.
"""

from __future__ import annotations

import logging
import os
from abc import ABC

from src.bot import MeshflowBot
from src.radio.events import IncomingTextMessage

TEXT_MESSAGE_MAX_HOPS = int(os.getenv("TEXT_MESSAGE_MAX_HOPS", "5"))
if TEXT_MESSAGE_MAX_HOPS < 1:
    logging.warning("TEXT_MESSAGE_MAX_HOPS is less than 1, capping at 1.")
    TEXT_MESSAGE_MAX_HOPS = 1
elif TEXT_MESSAGE_MAX_HOPS > 7:
    logging.warning(
        "TEXT_MESSAGE_MAX_HOPS is greater than the Meshtastic limit of 7. Capping at 7."
    )
    TEXT_MESSAGE_MAX_HOPS = 7


class AbstractBaseFeature(ABC):
    """Base class for commands and responders. Owns the messaging helpers."""

    bot: MeshflowBot

    def __init__(self, bot: MeshflowBot):
        self.bot = bot

    # --- channel ----------------------------------------------------------

    def reply_in_channel(
        self, message: IncomingTextMessage, response: str, want_ack: bool = False
    ) -> None:
        """Reply to ``message`` on the same channel it was received on."""
        self.message_in_channel(message.channel, response, want_ack)

    def message_in_channel(self, channel: int, response: str, want_ack: bool = False) -> None:
        logging.debug("Sending message: '%s'", response)
        self.bot.radio.send_text(
            response,
            channel=channel,
            want_ack=want_ack,
            hop_limit=TEXT_MESSAGE_MAX_HOPS,
        )

    # --- DM ---------------------------------------------------------------

    def reply_in_dm(
        self, message: IncomingTextMessage, response: str, want_ack: bool = False
    ) -> None:
        self.message_in_dm(message.from_id, response, want_ack)

    def message_in_dm(self, destination_id: str, response: str, want_ack: bool = False) -> None:
        logging.debug("Sending DM: '%s'", response)
        self.bot.radio.send_text(
            response,
            destination_id=destination_id,
            want_ack=want_ack,
            hop_limit=TEXT_MESSAGE_MAX_HOPS,
        )

    # --- reactions --------------------------------------------------------

    def react_in_channel(self, message: IncomingTextMessage, emoji: str) -> None:
        logging.debug("Reacting to message with emoji: '%s'", emoji)
        self.bot.radio.send_reaction(emoji, message.message_id, channel=message.channel)

    def react_in_dm(self, message: IncomingTextMessage, emoji: str) -> None:
        logging.debug("Reacting to message with emoji: '%s'", emoji)
        self.bot.radio.send_reaction(
            emoji, message.message_id, destination_id=message.from_id
        )
