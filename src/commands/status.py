import logging
from datetime import datetime, timezone
from src.commands.command import AbstractCommand

class StatusCommand(AbstractCommand):
    def __init__(self, bot):
        super().__init__(bot, "!status")

    def handle_packet(self, packet):
        from_id = packet.get('fromId')
        
        # Calculate Bot Uptime
        uptime = datetime.now(timezone.utc) - self.bot.start_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m"

        # Get Proxy Status
        proxy_info = "Disabled"
        if self.bot.proxy:
            status = self.bot.proxy.get_status()
            if isinstance(status, dict):
                state = "Online" if status['connected'] else "Reconnecting"
                proxy_info = f"{state}, {status['clients']} clients, {status['cached_kb']}KB cache, last radio {status['silence_secs']}s ago"
            else:
                proxy_info = status

        # Get Storage API status
        storage_info = "Not Configured"
        if self.bot.storage_apis:
            # We'll just report if at least one is configured
            storage_info = f"{len(self.bot.storage_apis)} API(s) active"

        response = (
            f"🤖 Bot Status:\n"
            f"⏱ Uptime: {uptime_str}\n"
            f"🔌 Proxy: {proxy_info}\n"
            f"☁️ Storage: {storage_info}"
        )

        logging.info(f"Sending status to {from_id}")
        self.reply_in_dm(packet, response)

    def get_command_for_logging(self, message: str) -> (str, list[str] | None, str | None):
        return self._gcfl_just_base_command(message)

