from src.bot import MeshflowBot
from src.commands.command import AbstractCommand
from src.radio.events import IncomingTextMessage


class HelloCommand(AbstractCommand):
    def __init__(self, bot: MeshflowBot):
        super().__init__(bot, "hello")

    def handle_packet(self, message: IncomingTextMessage) -> None:
        sender_id = message.from_id
        sender = self.bot.node_db.get_by_id(sender_id)
        sender_name = sender.long_name if sender else sender_id

        response = (
            f"Hello, {sender_name}! How can I help you? (tip: try !help). "
            f"I'm a bot maintained by PDY4 / pskillen@gmail.com"
        )
        self.message_in_dm(sender_id, response)

    def get_command_for_logging(self, message: str):
        return self._gcfl_just_base_command(message)
