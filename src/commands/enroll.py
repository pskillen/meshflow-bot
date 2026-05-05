from src.bot import MeshflowBot
from src.commands.command import AbstractCommandWithSubcommands
from src.persistence.user_prefs import UserPrefs
from src.radio.events import IncomingTextMessage


class EnrollCommandHandler(AbstractCommandWithSubcommands):
    def __init__(self, bot: MeshflowBot, base_command: str):
        super().__init__(bot, base_command)
        self.sub_commands["testing"] = self.enroll_testing

    def handle_base_command(
        self, message: IncomingTextMessage, args: list[str]
    ) -> None:
        self.show_help(message, [])

    def show_help(self, message: IncomingTextMessage, args: list[str]) -> None:
        response = (
            "!enroll: (or !leave) bot responds to you in public channels:\n"
            "!enroll testing: bot will like your msg if you say 'test' or 'testing'\n"
        )
        self.reply(message, response)

    def enroll_testing(
        self, message: IncomingTextMessage, args: list[str]
    ) -> None:
        sender_id = message.from_id
        user_prefs = self.bot.user_prefs_persistence.get_user_prefs(sender_id)
        if user_prefs is None:
            user_prefs = UserPrefs(sender_id)

        user_prefs.respond_to_testing.value = self.base_command == "enroll"
        self.bot.user_prefs_persistence.persist_user_prefs(sender_id, user_prefs)

        response = (
            f"You've been "
            f"{'enrolled' if user_prefs.respond_to_testing.value else 'unenrolled'} "
            "from responses to 'test' or 'testing' in public channels."
        )
        self.reply(message, response)

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_command_and_args(message)
