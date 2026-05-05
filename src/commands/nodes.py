from datetime import datetime, timezone

from src.bot import MeshflowBot
from src.commands.command import AbstractCommandWithSubcommands
from src.data_classes import MeshNode
from src.helpers import pretty_print_last_heard
from src.radio.events import IncomingTextMessage


class NodesCommand(AbstractCommandWithSubcommands):
    max_node_count_summary = 6
    max_node_count_detailed = 4

    def __init__(self, bot: MeshflowBot):
        super().__init__(bot, "nodes")
        self.sub_commands["busy"] = self.handle_busy

    def get_busy_nodes(self) -> list[MeshNode.User]:
        return sorted(
            self.bot.node_db.list_nodes(),
            key=lambda n: self.bot.node_info.get_node_packets_today(n.id),
            reverse=True,
        )

    def handle_base_command(
        self, message: IncomingTextMessage, args: list[str]
    ) -> None:
        nodes = self.bot.node_db.list_nodes()
        online_nodes = self.bot.node_info.get_online_nodes()
        offline_nodes = self.bot.node_info.get_offline_nodes()

        sorted_nodes = sorted(
            nodes,
            key=lambda n: self.bot.node_info.get_last_heard(n.id)
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        response = f"{len(online_nodes)} nodes online, {len(offline_nodes)} offline."
        response += "\nRecent nodes:\n"
        for node in sorted_nodes[: self.max_node_count_summary]:
            last_heard = self.bot.node_info.get_last_heard(node.id)
            response += f"- {node.short_name} ({pretty_print_last_heard(last_heard)})\n"

        self.reply(message, response)

    def handle_busy(self, message: IncomingTextMessage, args: list[str]) -> None:
        sender = message.from_id

        if len(args) == 0:
            self.send_busy_node_list(sender)
        elif args[0] == "detailed":
            busy_nodes = self.get_busy_nodes()
            for node in busy_nodes[: self.max_node_count_detailed]:
                self.send_detailed_nodeinfo(sender, node.id)
        else:
            node = self.bot.node_db.get_by_short_name(args[0])
            if not node:
                response = (
                    f"Unknown command: !nodes busy '{' '.join(args)}' - "
                    "valid args are 'detailed' or (node ID)"
                )
                return self.reply(message, response)
            self.send_detailed_nodeinfo(sender, node.id)

    def send_busy_node_list(self, sender: str) -> None:
        online_nodes = self.bot.node_info.get_online_nodes()

        busy_nodes = self.get_busy_nodes()
        response = f"{len(online_nodes)} nodes online."
        response += "\nBusy nodes:\n"
        for node in busy_nodes[: self.max_node_count_summary]:
            packets_today = self.bot.node_info.get_node_packets_today(node.id)
            response += f"- {node.short_name} ({packets_today} pkts)\n"

        response += (
            f"(last reset at {self.bot.node_info.packet_counter_reset_time.strftime('%H:%M:%S')})"
        )
        self.reply_to(sender, response)

    def send_detailed_nodeinfo(self, sender: str, node_id: str) -> None:
        node = self.bot.node_db.get_by_id(node_id)
        if not node:
            return

        packets_today = self.bot.node_info.get_node_packets_today(node.id)
        packet_breakdown_today = self.bot.node_info.get_node_packets_today_breakdown(
            node.id
        )
        last_heard = self.bot.node_info.get_last_heard(node.id)

        response = f"{node.long_name} ({node.short_name})\n"
        response += f"Last heard: {pretty_print_last_heard(last_heard)}\n"
        response += f"Pkts today: {packets_today}\n"

        sorted_breakdown = sorted(
            packet_breakdown_today.items(), key=lambda x: x[1], reverse=True
        )
        for packet_type, count in sorted_breakdown:
            response += f"- {packet_type}: {count}\n"

        self.reply_to(sender, response)

    def show_help(self, message: IncomingTextMessage, args: list[str]) -> None:
        help_text = "!nodes: details about nodes this device has seen\n"
        help_text += "!nodes busy: summary of busiest nodes\n"
        help_text += "!nodes busy detailed: detailed info about busiest nodes\n"
        self.reply(message, help_text)

    def get_command_for_logging(self, message: str):
        return self._gcfl_base_onesub_args(message)
