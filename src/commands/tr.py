import logging
import threading
import time
from meshtastic.protobuf.mesh_pb2 import MeshPacket

from src.commands.command import AbstractCommand


class TracerouteCommand(AbstractCommand):
    def __init__(self, bot):
        super().__init__(bot, 'tr')

    def handle_packet(self, packet: MeshPacket) -> None:
        hop_start = packet.get('hopStart', 0)
        hop_limit = packet.get('hopLimit', 0)
        hops_away = hop_start - hop_limit
        
        snr = packet.get('rxSnr', 0.0)
        
        sender_id = packet['fromId']
        sender = self.bot.node_db.get_by_id(sender_id)
        sender_name = sender.long_name if sender else sender_id

        if hops_away == 0:
            response = f"{sender_name} you are Zero Hops from me. No traceroute required!"
            self.reply_in_dm(packet, response)
            return

        response = f"{sender_name} you are {hops_away} hops away (Signal: {snr} dB). Starting full traceroute..."
        self.reply_in_dm(packet, response)
        
        # Initiate actual traceroute
        self.bot.pending_traces[sender_id] = sender_id
        
        # Start a timeout timer (90 seconds)
        def check_timeout():
            time.sleep(90)
            if sender_id in self.bot.pending_traces:
                # If still in pending_traces, we never got a response
                del self.bot.pending_traces[sender_id]
                logging.info(f"Traceroute to {sender_id} timed out.")
                timeout_msg = f"Traceroute to {sender_id} timed out (no response from mesh)."
                self.message_in_dm(sender_id, timeout_msg)

        threading.Thread(target=check_timeout, daemon=True).start()

        try:
            logging.info(f"Initiating traceroute to {sender_id}")
            # hopLimit=7 is standard max
            self.bot.interface.sendTraceRoute(sender_id, hopLimit=7)
        except Exception as e:
            logging.error(f"Failed to send traceroute to {sender_id}: {e}")
            if sender_id in self.bot.pending_traces:
                del self.bot.pending_traces[sender_id]
            self.reply_in_dm(packet, f"Error starting traceroute: {e}")

    def get_command_for_logging(self, message: str) -> (str, list[str] | None, str | None):
        return self._gcfl_just_base_command(message)
