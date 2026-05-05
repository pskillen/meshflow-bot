import random

from src.bot import MeshflowBot
from src.radio.events import IncomingTextMessage
from src.responders.responder import AbstractResponder


class MessageReactionResponder(AbstractResponder):
    emoji: str

    def __init__(self, bot: MeshflowBot, emoji: str):
        super().__init__(bot)
        self.emoji = emoji

    def handle_packet(self, message: IncomingTextMessage) -> bool:
        if not self._is_enrolled(message.from_id):
            return False

        emoji = random.choice(self.emoji)
        self.react_in_channel(message, emoji)
        return True

    def _is_enrolled(self, from_id: str) -> bool:
        user_prefs = self.bot.user_prefs_persistence.get_user_prefs(from_id)
        if not user_prefs:
            return False
        return user_prefs.respond_to_testing.value
