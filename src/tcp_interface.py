import logging
import sys
from pubsub import pub
import time
from queue import Queue
from typing import Optional, Callable, Union

from meshtastic import BROADCAST_ADDR
from meshtastic.protobuf import portnums_pb2, mesh_pb2
from meshtastic.tcp_interface import TCPInterface


class SupportsMessageReactionInterface(TCPInterface):
    def sendReaction(
            self,
            emoji: str,
            messageId: int,
            destinationId: Union[int, str] = BROADCAST_ADDR,
            wantAck: bool = False,
            channelIndex: int = 0,
            portNum: portnums_pb2.PortNum.ValueType = portnums_pb2.PortNum.TEXT_MESSAGE_APP,
            hopLimit: Optional[int] = None,
            pkiEncrypted: Optional[bool] = False,
            publicKey: Optional[bytes] = None,
    ):
        emoji_bytes = emoji.encode('utf-8')

        packet = mesh_pb2.MeshPacket()
        packet.channel = channelIndex
        packet.decoded.portnum = portNum
        packet.decoded.payload = emoji_bytes
        packet.decoded.reply_id = messageId
        packet.decoded.emoji = True

        self._sendPacket(packet, destinationId,
                         wantAck=wantAck,
                         hopLimit=hopLimit,
                         pkiEncrypted=pkiEncrypted,
                         publicKey=publicKey)
        return packet


class AutoReconnectTcpInterface(SupportsMessageReactionInterface, TCPInterface):
    packet_queue: Queue

    def __init__(self, *args,
                 error_handler: Optional[Callable[[Exception], None]] = None,
                 packet_queue: Optional[Queue] = None,
                 **kwargs):
        self.error_handler = error_handler
        self.packet_queue = packet_queue or Queue()
        super().__init__(*args, **kwargs)

        # if there were packets from an old connection, play them now
        self._replay_packet_queue()

        # TODO: thing to try #1
        # we shouldn't actually call self.connect() -> let's try self.myConnect()
        # Nah: calling .myConnect() doesn't seem to do anything
        # Calling .connect() throws an error about not being able to restart a thread
        # TODO: thing to try #2
        # Store packets in a queue and resend them after reconnecting
        # This will involve exposing the queue, and reloading the queue in bot.py since we create a new interface object

    def onResponseTraceRoute(self, packet):
        """
        Callback for when a traceroute response is received.
        """
        try:
            route_discovery = None
            if isinstance(packet, dict):
                decoded = packet.get('decoded', {})
                # It might be in 'routing', 'routing_app', or 'traceroute'
                route_discovery = decoded.get('routing') or decoded.get('routing_app') or decoded.get('traceroute')
                
                if not route_discovery and 'payload' in decoded:
                    logging.debug(f"onResponseTraceRoute: Route not found in decoded, full packet: {packet}")
            elif hasattr(packet, 'decoded'):
                route_discovery = getattr(packet.decoded, 'routing', 
                                          getattr(packet.decoded, 'routing_app', 
                                                  getattr(packet.decoded, 'traceroute', None)))

            logging.info(f"onResponseTraceRoute: Received traceroute response. Route data present: {route_discovery is not None}")
            
            # Always call super to allow library internal processing (printing to stdout etc)
            super().onResponseTraceRoute(packet)
            
            # Notify bot logic
            pub.sendMessage("meshtastic.traceroute", packet=packet, route=route_discovery)
        except Exception as e:
            logging.error(f"Error in onResponseTraceRoute: {e}", exc_info=True)

    def sendHeartbeat(self):
        try:
            super().sendHeartbeat()
        except (OSError, BrokenPipeError) as e:
            logging.error(f"Heartbeat failed: {e}")
            # TODO: Decide if we want to handle the error on this thread
            # self._reconnect_with_backoff()
            self._shutdown_and_call_error_handler()

    def _sendPacket(
            self,
            meshPacket: mesh_pb2.MeshPacket,
            destinationId: Union[int, str] = BROADCAST_ADDR,
            wantAck: bool = False,
            hopLimit: Optional[int] = None,
            pkiEncrypted: Optional[bool] = False,
            publicKey: Optional[bytes] = None,
    ):
        port_val = meshPacket.decoded.portnum
        logging.info(f"_sendPacket: Attempting to send Port {port_val} to {destinationId} (wantAck={wantAck})")
        try:
            super()._sendPacket(
                meshPacket=meshPacket,
                destinationId=destinationId,
                wantAck=wantAck,
                hopLimit=hopLimit,
                pkiEncrypted=pkiEncrypted,
                publicKey=publicKey
            )
            logging.info(f"_sendPacket: Successfully handed Port {port_val} to {destinationId} to meshtastic library")
        except (OSError, BrokenPipeError) as e:
            logging.error(f"_sendPacket failed (connection error): {e}")
            self.packet_queue.put((meshPacket, destinationId, wantAck, hopLimit, pkiEncrypted, publicKey))
            self._shutdown_and_call_error_handler(e)
        except Exception as e:
            logging.error(f"_sendPacket failed (unexpected error): {e}", exc_info=True)
            # We still queue it just in case it's recoverable
            self.packet_queue.put((meshPacket, destinationId, wantAck, hopLimit, pkiEncrypted, publicKey))

    def _shutdown_and_call_error_handler(self, conn_error: Optional[Exception] = None):
        try:
            self.close()
            self._disconnected()
        except Exception as e:
            logging.warning(
                f"Failed to close connection. "
                f"This might not be an issue since we've already disconnected: {e}")

        if self.error_handler:
            self.error_handler(conn_error)

    def _reconnect_with_backoff(self):
        logging.info("Attempting to reconnect...")
        backoff_time = 5  # Initial back-off time in seconds
        max_backoff_time = 300  # Maximum back-off time in seconds (5 minutes)
        backoff_rate = 1.5  # Exponential back-off rate

        while True:
            try:
                self.myConnect()
                self.connect()
                logging.info("Reconnected successfully")
                self._replay_packet_queue()
                break
            except Exception as e:
                logging.error(f"Reconnection attempt failed: {e}")
                if backoff_time == max_backoff_time:
                    logging.error("Max backoff time reached. Exiting.")
                    sys.exit(1)
                backoff_time = min(backoff_time * backoff_rate, max_backoff_time)  # Exponential back-off
                logging.info(f"Next reconnection attempt in {backoff_time} seconds")
                time.sleep(backoff_time)

    def _replay_packet_queue(self):
        while not self.packet_queue.empty():
            packet, destinationId, wantAck, hopLimit, pkiEncrypted, publicKey = self.packet_queue.get()
            try:
                super()._sendPacket(
                    meshPacket=packet,
                    destinationId=destinationId,
                    wantAck=wantAck,
                    hopLimit=hopLimit,
                    pkiEncrypted=pkiEncrypted,
                    publicKey=publicKey
                )
                logging.info("Replayed packet successfully")
            except Exception as e:
                logging.error(f"Failed to replay packet: {e}")
                self.packet_queue.put((packet, destinationId, wantAck, hopLimit, pkiEncrypted, publicKey))
                break
