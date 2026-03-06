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
        
        is_public = packet.get('toId') == '^all' or 'channel' in packet
        
        def send_reply(msg):
            # Always reply in DM
            self.reply_in_dm(packet, msg, want_ack=True)

        # Add a reaction (thumbs up for public to acknowledge without spamming, hourglass for DM)
        reaction_emoji = "👍" if is_public else "⌛"
        reaction_dest = packet.get('toId') if is_public else packet.get('fromId')
        logging.info(f"Adding reaction {reaction_emoji} for packet {packet.get('id')} to {reaction_dest}")
        self.bot.interface.sendReaction(reaction_emoji, messageId=packet['id'], destinationId=reaction_dest)

        requester_id = packet.get('fromId')
        requester = self.bot.node_db.get_by_id(requester_id)
        requester_name = requester.long_name if requester else requester_id

        target_node = None
        if len(words) > 1:
            target_short = words[1]
            target_node = self.bot.get_node_by_short_name(target_short)
            if not target_node:
                send_reply(f"Could not find node with short name '{target_short}'")
                return
            target_id = target_node.id
            target_long_name = target_node.long_name
        else:
            target_id = requester_id
            target_long_name = requester_name

        if target_id == self.bot.my_id:
            send_reply("I am already here! No traceroute required.")
            return

        # If tracing back to requester, we can show hops_away/SNR from the incoming packet
        if target_id == requester_id:
            hop_start = packet.get('hopStart', 0)
            hop_limit = packet.get('hopLimit', 0)
            hops_away = hop_start - hop_limit
            snr = packet.get('rxSnr', 0.0)

            # We can log this, but no need to send it explicitly over the radio to save airtime
            logging.info(f"Detected {hops_away} hops for {target_id}. SNR: {snr}dB.")
        else:
            # Tracing to a different node
            logging.info(f"Starting traceroute to {target_long_name} ({target_id}) for you...")
        
        # Store for the callback
        if target_id not in self.bot.pending_traces:
            self.bot.pending_traces[target_id] = []
        
        # Store context: force is_public=False so bot.py always replies via DM
        to_id = packet.get('toId')
        channel_index = packet.get('channel', 0)
        context = (requester_id, False, to_id, channel_index)
        
        if context not in self.bot.pending_traces[target_id]:
            self.bot.pending_traces[target_id].append(context)
        
        # Start a timeout timer (120 seconds)
        def check_timeout():
            time.sleep(120)
            if target_id in self.bot.pending_traces:
                # Find and remove this specific context from the pending list
                self.bot.pending_traces[target_id] = [c for c in self.bot.pending_traces[target_id] if c[0] != requester_id]
                # If no more requesters for this target, clean up the key
                if not self.bot.pending_traces[target_id]:
                    del self.bot.pending_traces[target_id]
                
                logging.info(f"Traceroute to {target_id} (requested by {requester_id}) timed out.")
                timeout_msg = f"Traceroute to {target_long_name} ({target_id}) timed out (no response from mesh)."
                
                # Send the timeout message in a separate thread to avoid blocking the timer/interface
                def send_timeout():
                    self.message_in_dm(requester_id, timeout_msg, want_ack=True)
                
                threading.Thread(target=send_timeout, daemon=True).start()

        threading.Thread(target=check_timeout, daemon=True).start()

        try:
            # Let the reaction settle before firing the trace
            time.sleep(2)
            logging.info(f"Initiating traceroute to {target_id} requested by {requester_id}")
            # hopLimit=7 is standard max
            p = self.bot.interface.sendTraceRoute(target_id, hopLimit=7)
            if p:
                logging.info(f"Sent traceroute packet to {target_id}. Packet ID: {p.id}")
            else:
                logging.warning(f"sendTraceRoute returned None for {target_id}")
        except Exception as e:
            logging.error(f"Failed to send traceroute to {target_id}: {e}")
            if target_id in self.bot.pending_traces and requester_id in self.bot.pending_traces[target_id]:
                self.bot.pending_traces[target_id].remove(requester_id)
                if not self.bot.pending_traces[target_id]:
                    del self.bot.pending_traces[target_id]
                send_reply(f"Error starting traceroute: {e}")

    def get_command_for_logging(self, message: str) -> (str, list[str] | None, str | None):
        return self._gcfl_base_command_and_args(message)
