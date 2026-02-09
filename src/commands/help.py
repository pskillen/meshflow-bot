from meshtastic.protobuf.mesh_pb2 import MeshPacket

from src.bot import MeshtasticBot
from src.commands.command import AbstractCommandWithSubcommands
from src.helpers import get_env_bool


class HelpCommand(AbstractCommandWithSubcommands):
    def __init__(self, bot: MeshtasticBot):
        super().__init__(bot, 'help')
        if get_env_bool('ENABLE_COMMAND_HELLO', True):
            self.sub_commands['hello'] = self.handle_hello
        if get_env_bool('ENABLE_COMMAND_PING', True):
            self.sub_commands['ping'] = self.handle_ping
        if get_env_bool('ENABLE_COMMAND_TR', True):
            self.sub_commands['tr'] = self.handle_tr
        if get_env_bool('ENABLE_COMMAND_NODES', True):
            self.sub_commands['nodes'] = self.handle_nodes
        if get_env_bool('ENABLE_COMMAND_WHOAMI', True):
            self.sub_commands['whoami'] = self.handle_whoami
        if get_env_bool('ENABLE_COMMAND_PREFS', True):
            self.sub_commands['prefs'] = self.handle_prefs
        if get_env_bool('ENABLE_COMMAND_STATUS', True):
            self.sub_commands['status'] = self.handle_status
        # if get_env_bool('ENABLE_COMMAND_ENROLL', True):
        #     self.sub_commands['enroll'] = self.handle_enroll
        # if get_env_bool('ENABLE_COMMAND_LEAVE', True):
        #     self.sub_commands['leave'] = self.handle_leave

    def handle_base_command(self, packet: MeshPacket, args: list[str]) -> None:
        subcmds = self.sub_commands.keys()
        subcmds = filter(None, subcmds)  # remove empty strings
        subcmds = [f"!{cmd}" for cmd in subcmds]

        public_cmds = []
        if get_env_bool('ENABLE_COMMAND_TR', True):
            public_cmds.append("!tr")
        if get_env_bool('ENABLE_COMMAND_PING', True):
            public_cmds.append("!ping")
        if get_env_bool('ENABLE_COMMAND_HELLO', True):
            public_cmds.append("!hello")
        if get_env_bool('ENABLE_COMMAND_NODES', True):
            public_cmds.append("!nodes")
        if get_env_bool('ENABLE_COMMAND_STATUS', True):
            public_cmds.append("!status")
        if get_env_bool('ENABLE_COMMAND_WHOAMI', True):
            public_cmds.append("!whoami")

        response = f"Available via Direct Message: {', '.join(subcmds)}."
        if public_cmds:
            response += f"\nAvailable in Public Channels: {', '.join(public_cmds)} (replies via DM)."
        
        self.reply(packet, response)

    def handle_hello(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!hello: responds with a greeting"
        self.reply(packet, response)

    def handle_ping(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!ping (+ optional correlation message): responds with a pong"
        self.reply(packet, response)

    def handle_tr(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!tr: responds with the number of hops and signal strength of your message"
        self.reply(packet, response)

    def handle_nodes(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!nodes: details about the nodes this device has seen"
        self.reply(packet, response)

    def show_help(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!help: show this help message"
        self.reply(packet, response)

    def handle_whoami(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!whoami: show details about yourself"
        self.reply(packet, response)

    def handle_prefs(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!prefs: show and update your user preferences"
        self.reply(packet, response)

    def handle_enroll(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!enroll: bot will respond to certain messages from you on public channels"
        self.reply(packet, response)

    def handle_leave(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!leave: bot will not respond to you on public channels"
        self.reply(packet, response)

    def handle_status(self, packet: MeshPacket, args: list[str]) -> None:
        response = "!status: show current bot and proxy health status"
        self.reply(packet, response)

    def get_command_for_logging(self, message: str) -> (str, list[str] | None, str | None):
        return self._gcfl_base_command_and_args(message)
