import logging
import threading
import time
from meshtastic.protobuf.mesh_pb2 import MeshPacket

from src.commands.command import AbstractCommand


class TracerouteCommand(AbstractCommand):
    def __init__(self, bot):
        super().__init__(bot, 'tr')

    def handle_packet(self, packet: MeshPacket) -> None:
        message = packet['decoded']['text']
        words = message.split()
        
        # Add a reaction to show we are working on it
        self.bot.interface.sendReaction("⌛", messageId=packet['id'], destinationId=packet['fromId'])

        requester_id = packet['fromId']
        requester = self.bot.node_db.get_by_id(requester_id)
        requester_name = requester.long_name if requester else requester_id

        target_node = None
        if len(words) > 1:
            target_short = words[1]
            target_node = self.bot.get_node_by_short_name(target_short)
            if not target_node:
                self.reply_in_dm(packet, f"Could not find node with short name '{target_short}'")
                return
            target_id = target_node.id
            target_long_name = target_node.long_name
        else:
            target_id = requester_id
            target_long_name = requester_name

        if target_id == self.bot.my_id:
            self.reply_in_dm(packet, "I am already here! No traceroute required.")
            return

        # If tracing back to requester, we can show hops_away/SNR from the incoming packet
        if target_id == requester_id:
            hop_start = packet.get('hopStart', 0)
            hop_limit = packet.get('hopLimit', 0)
            hops_away = hop_start - hop_limit
            snr = packet.get('rxSnr', 0.0)

            if hops_away == 0:
                response = f"{requester_name} you are Zero Hops from me. No traceroute required!"
                self.reply_in_dm(packet, response)
                return

            response = f"{requester_name} you are {hops_away} hops away (Signal: {snr} dB). Starting full traceroute..."
            self.reply_in_dm(packet, response)
        else:
            # Tracing to a different node
            response = f"Starting traceroute to {target_long_name} ({target_id}) for you..."
            self.reply_in_dm(packet, response)
        
        # Initiate actual traceroute
        # Map target_id -> list of requester_ids
        if target_id not in self.bot.pending_traces:
            self.bot.pending_traces[target_id] = []
        
        if requester_id not in self.bot.pending_traces[target_id]:
            self.bot.pending_traces[target_id].append(requester_id)
        
        # Start a timeout timer (90 seconds)
        def check_timeout():
            time.sleep(90)
            if target_id in self.bot.pending_traces and requester_id in self.bot.pending_traces[target_id]:
                # Remove this specific requester from the pending list
                self.bot.pending_traces[target_id].remove(requester_id)
                # If no more requesters for this target, clean up the key
                if not self.bot.pending_traces[target_id]:
                    del self.bot.pending_traces[target_id]
                
                logging.info(f"Traceroute to {target_id} (requested by {requester_id}) timed out.")
                timeout_msg = f"Traceroute to {target_long_name} ({target_id}) timed out (no response from mesh)."
                
                # Send the timeout message in a separate thread to avoid blocking the timer/interface
                def send_timeout():
                    self.message_in_dm(requester_id, timeout_msg)
                
                threading.Thread(target=send_timeout, daemon=True).start()

        threading.Thread(target=check_timeout, daemon=True).start()

        try:
            logging.info(f"Initiating traceroute to {target_id} requested by {requester_id}")
            # hopLimit=7 is standard max
            self.bot.interface.sendTraceRoute(target_id, hopLimit=7)
        except Exception as e:
            logging.error(f"Failed to send traceroute to {target_id}: {e}")
            if target_id in self.bot.pending_traces and requester_id in self.bot.pending_traces[target_id]:
                self.bot.pending_traces[target_id].remove(requester_id)
                if not self.bot.pending_traces[target_id]:
                    del self.bot.pending_traces[target_id]
            self.reply_in_dm(packet, f"Error starting traceroute: {e}")

    def get_command_for_logging(self, message: str) -> (str, list[str] | None, str | None):
        return self._gcfl_base_command_and_args(message)
