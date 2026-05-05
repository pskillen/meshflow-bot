"""Command base classes."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod

from src.base_feature import AbstractBaseFeature
from src.bot import MeshflowBot
from src.radio.events import IncomingTextMessage


class AbstractCommand(AbstractBaseFeature, ABC):
    base_command: str

    def __init__(self, bot: MeshflowBot, base_command: str):
        super().__init__(bot)
        self.base_command = base_command

    @abstractmethod
    def handle_packet(self, message: IncomingTextMessage) -> None:
        """Handle the inbound text message that triggered this command."""

    # Legacy aliases kept so existing command bodies (admin, help, nodes, …)
    # don't all need touching at the same time. New code should call
    # ``reply_in_dm`` / ``message_in_dm`` directly.
    def reply(
        self, message: IncomingTextMessage, response: str, want_ack: bool = False
    ) -> None:
        self.reply_in_dm(message, response, want_ack)

    def reply_to(
        self, destination_id: str, response: str, want_ack: bool = False
    ) -> None:
        self.message_in_dm(destination_id, response, want_ack)

    @abstractmethod
    def get_command_for_logging(
        self, message: str
    ) -> tuple[str, list[str] | None, str | None]:
        """Extract the command, subcommands, and arguments for the audit log."""

    def _gcfl_just_base_command(
        self, _message: str
    ) -> tuple[str, list[str] | None, str | None]:
        return self.base_command, None, None

    def _gcfl_base_command_and_args(
        self, message: str
    ) -> tuple[str, list[str] | None, str | None]:
        cmd = self.base_command
        if len(message) > len(self.base_command) + 1:
            args = message[len(self.base_command) + 1 :].strip()
        else:
            args = None
        return cmd, None, args

    def _gcfl_base_onesub_args(
        self, message: str
    ) -> tuple[str, list[str] | None, str | None]:
        tokens = message.split()
        cmd = self.base_command
        subcommand = [tokens[1]] if len(tokens) > 1 else None
        args = " ".join(tokens[2:]) if len(tokens) > 2 else None
        return cmd, subcommand, args


class AbstractCommandWithSubcommands(AbstractCommand, ABC):
    sub_commands: dict[str, callable]

    def __init__(
        self,
        bot: MeshflowBot,
        base_command_str: str,
        error_on_invalid_subcommand: bool = True,
    ):
        super().__init__(bot, base_command_str)
        self.sub_commands = {
            "": self.handle_base_command,
            "help": self.show_help,
        }
        self.error_on_invalid_subcommand = error_on_invalid_subcommand

    def handle_packet(self, message: IncomingTextMessage) -> None:
        words = message.text.split()
        if len(words) < 2:
            sub_command_name = ""
            args: list[str] = []
        else:
            sub_command_name = words[1].lstrip("!")
            args = words[2:] if len(words) > 2 else []

        sub_command = self.sub_commands.get(sub_command_name)
        if sub_command:
            num_args = len(inspect.signature(sub_command).parameters)
            if num_args == 2:
                sub_command(message, args)
            elif num_args == 3:
                sub_command(message, args, sub_command_name)
            else:
                raise ValueError(
                    f"Subcommand '{sub_command_name}' has an unexpected number of arguments"
                )
        else:
            if self.error_on_invalid_subcommand:
                self.reply_in_dm(message, f"Unknown command '{sub_command_name}'")
            else:
                return self.show_help(message, args)

    @abstractmethod
    def handle_base_command(
        self, message: IncomingTextMessage, args: list[str]
    ) -> None:
        pass

    @abstractmethod
    def show_help(self, message: IncomingTextMessage, args: list[str]) -> None:
        pass
