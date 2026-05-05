from src.bot import MeshflowBot
from src.commands.command import AbstractCommandWithSubcommands
from src.radio.events import IncomingTextMessage


class HelpCommand(AbstractCommandWithSubcommands):
    def __init__(self, bot: MeshflowBot):
        super().__init__(bot, "help")
        self.sub_commands["hello"] = self.handle_hello
        self.sub_commands["ping"] = self.handle_ping
        self.sub_commands["nodes"] = self.handle_nodes
        self.sub_commands["whoami"] = self.handle_whoami
        self.sub_commands["prefs"] = self.handle_prefs

    def handle_base_command(
        self, message: IncomingTextMessage, args: list[str]
    ) -> None:
        subcmds = self.sub_commands.keys()
        subcmds = filter(None, subcmds)
        subcmds = [f"!{cmd}" for cmd in subcmds]
        self.reply(message, f"Valid commands are: {', '.join(subcmds)}")

    def handle_hello(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "!hello: responds with a greeting")

    def handle_ping(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(
            message, "!ping (+ optional correlation message): responds with a pong"
        )

    def handle_nodes(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "!nodes: details about the nodes this device has seen")

    def show_help(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "!help: show this help message")

    def handle_whoami(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "!whoami: show details about yourself")

    def handle_prefs(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "!prefs: show and update your user preferences")

    def handle_enroll(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(
            message,
            "!enroll: bot will respond to certain messages from you on public channels",
        )

    def handle_leave(self, message: IncomingTextMessage, args: list[str]) -> None:
        self.reply(message, "!leave: bot will not respond to you on public channels")

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_command_and_args(message)
