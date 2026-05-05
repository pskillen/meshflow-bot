from src.bot import MeshflowBot
from src.commands.command import AbstractCommandWithSubcommands
from src.persistence.user_prefs import UserPrefs
from src.radio.events import IncomingTextMessage


class PrefsCommandHandler(AbstractCommandWithSubcommands):
    def __init__(self, bot: MeshflowBot):
        super().__init__(bot, "prefs", error_on_invalid_subcommand=False)
        self.sub_commands["testing"] = self.set_boolean_pref

    def handle_base_command(
        self, message: IncomingTextMessage, args: list[str]
    ) -> None:
        sender_id = message.from_id
        user_prefs = self.bot.user_prefs_persistence.get_user_prefs(sender_id)
        if user_prefs is None:
            user_prefs = UserPrefs(sender_id)

        response = (
            "Your preferences:\n"
            f"Respond to 'testing': "
            f"{'enabled' if user_prefs.respond_to_testing.value else 'disabled'}\n"
        )
        self.reply(message, response)

    def set_boolean_pref(
        self,
        message: IncomingTextMessage,
        args: list[str],
        sub_command_name: str,
    ) -> None:
        if len(args) == 0:
            return self.show_help(message, args)

        pref_name = sub_command_name
        value_str = args[0].lower()
        if value_str not in ["enable", "disable"]:
            return self.reply(
                message,
                f"Invalid mode for '{sub_command_name}'. Please specify 'enable' or 'disable'.",
            )
        value_bool = value_str == "enable"

        sender_id = message.from_id
        user_prefs = self.bot.user_prefs_persistence.get_user_prefs(sender_id)
        if user_prefs is None:
            user_prefs = UserPrefs(sender_id)

        if pref_name == "testing":
            user_prefs.respond_to_testing.value = value_bool
            response = (
                f"You've {'enabled' if user_prefs.respond_to_testing.value else 'disabled'} "
                "bot responses to 'test' or 'testing' in public channels."
            )
        else:
            return

        self.bot.user_prefs_persistence.persist_user_prefs(sender_id, user_prefs)
        self.reply(message, response)

    def show_help(self, message: IncomingTextMessage, args: list[str]) -> None:
        response = (
            "!prefs: configure bot settings related to your node:\n"
            "!prefs testing enable/disable: bot will like your msg if you say "
            "'test' or 'testing'\n"
        )
        self.reply(message, response)

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_command_and_args(message)
