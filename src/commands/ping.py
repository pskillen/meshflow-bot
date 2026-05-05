from src.commands.command import AbstractCommand
from src.radio.events import IncomingTextMessage


class PingCommand(AbstractCommand):
    def __init__(self, bot):
        super().__init__(bot, "ping")

    def handle_packet(self, message: IncomingTextMessage) -> None:
        text = message.text
        hops_away = message.hops_away

        self.react_in_dm(message, "🏓")

        # trim off the '!ping' command from the message
        additional = text[5:].strip()

        response = "!pong"
        if additional:
            response = f"!pong: {additional}"

        response += f" (ping took {hops_away} hops)"
        self.reply_in_dm(message, response)

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_command_and_args(message)
