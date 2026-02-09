import importlib
from src.helpers import get_env_bool


class CommandFactory:
    commands = {
        "!ping": {
            "class": "src.commands.ping.PingCommand",
            "args": []
        },
        "!tr": {
            "class": "src.commands.tr.TracerouteCommand",
            "args": []
        },
        "!hello": {
            "class": "src.commands.hello.HelloCommand",
            "args": []
        },
        "!help": {
            "class": "src.commands.help.HelpCommand",
            "args": []
        },
        "!nodes": {
            "class": "src.commands.nodes.NodesCommand",
            "args": []
        },
        "!whoami": {
            "class": "src.commands.template.WhoAmI",
            "args": []
        },
        "!prefs": {
            "class": "src.commands.prefs.PrefsCommandHandler",
            "args": []
        },
        "!admin": {
            "class": "src.commands.admin.AdminCommand",
            "args": []
        },
        "!status": {
            "class": "src.commands.status.StatusCommand",
            "args": []
        },
        # "!enroll": {
        #     "class": "src.commands.enroll.EnrollCommandHandler",
        #     "args": ["enroll"]
        # },
        # "!leave": {
        #     "class": "src.commands.enroll.EnrollCommandHandler",
        #     "args": ["leave"]
        # },
    }

    @staticmethod
    def create_command(command_name, bot):
        command_info = CommandFactory.commands.get(command_name)
        if command_info:
            # Check if command is enabled via environment variable
            # e.g., !ping -> ENABLE_COMMAND_PING
            env_var_name = f"ENABLE_COMMAND_{command_name.lstrip('!').upper()}"
            if not get_env_bool(env_var_name, True):
                return None

            module_name, class_name = command_info["class"].rsplit('.', 1)
            module = importlib.import_module(module_name)
            command_class = getattr(module, class_name)
            args = [bot] + command_info["args"]
            return command_class(*args)
        return None
