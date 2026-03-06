import logging
import sys
import time
import threading
from datetime import datetime, timezone

import schedule
from meshtastic.protobuf.mesh_pb2 import MeshPacket
from pubsub import pub
from requests import HTTPError

from src.api.StorageAPI import StorageAPIWrapper
from src.commands.factory import CommandFactory
from src.data_classes import MeshNode
from src.helpers import pretty_print_last_heard, safe_encode_node_name, get_env_bool, get_env_int
from src.persistence.commands_logger import AbstractCommandLogger
from src.persistence.node_db import AbstractNodeDB
from src.persistence.node_info import AbstractNodeInfoStore
from src.persistence.packet_dump import dump_packet
from src.persistence.user_prefs import AbstractUserPrefsPersistence
from src.responders.responder_factory import ResponderFactory
from src.tcp_interface import AutoReconnectTcpInterface, SupportsMessageReactionInterface


class MeshtasticBot:
    admin_nodes: list[str]

    interface: SupportsMessageReactionInterface
    init_complete: bool

    my_id: str
    my_nodenum: int
    node_db: AbstractNodeDB
    node_info: AbstractNodeInfoStore
    command_logger: AbstractCommandLogger

    user_prefs_persistence: AbstractUserPrefsPersistence

    storage_apis: list[StorageAPIWrapper]

    def __init__(self, address: str):
        self.address = address
        self.start_time = datetime.now(timezone.utc)
        self.proxy = None

        self.admin_nodes = []

        self.interface = None
        self.init_complete = False

        self.my_id = None
        self.my_nodenum = None
        self.node_db = None
        self.node_info = None
        self.command_logger = None
        self.user_prefs_persistence = None
        self.storage_apis = []
        self.pending_traces = {}
        self.last_report_zero = False

        pub.subscribe(self.on_receive, "meshtastic.receive")
        pub.subscribe(self.on_traceroute, "meshtastic.traceroute")
        pub.subscribe(self.on_receive_text, "meshtastic.receive.text")
        pub.subscribe(self.on_node_updated, "meshtastic.node.updated")
        pub.subscribe(self.on_connection, "meshtastic.connection.established")

    def connect(self):
        logging.info(f"Connecting to Meshtastic node at {self.address}...")
        self.init_complete = False

        old_packet_queue = None
        if self.interface and hasattr(self.interface, 'packet_queue'):
            old_packet_queue = self.interface.packet_queue

        self.interface = AutoReconnectTcpInterface(
            hostname=self.address,
            error_handler=self._handle_interface_error,
            packet_queue=old_packet_queue,
        )

        logging.info("Connected. Listening for messages...")

    def _handle_interface_error(self, error):
        self.disconnect()

        logging.error(f"Handling interface error: {error}")
        backoff_time = 5  # Initial back-off time in seconds
        max_backoff_time = 300  # Maximum back-off time in seconds (5 minutes)
        backoff_rate = 1.5  # Exponential back-off rate

        while True:
            try:
                self.connect()
                self.init_complete = True
                logging.info("Reconnected successfully")
                break
            except Exception as e:
                logging.error(f"Reconnection attempt failed: {e}")
                if backoff_time == max_backoff_time:
                    logging.error("Max backoff time reached. Exiting.")
                    sys.exit(1)
                backoff_time = min(backoff_time * backoff_rate, max_backoff_time)  # Exponential back-off
                logging.info(f"Next reconnection attempt in {backoff_time} seconds")
                time.sleep(backoff_time)

    def disconnect(self):
        self.init_complete = False
        try:
            if self.interface:
                self.interface.close()
                self.interface._disconnected()
        except OSError as ex:
            logging.warning(f"Failed to close connection. Continuing anyway: {ex}")

    def on_connection(self, interface, topic=pub.AUTO_TOPIC):
        self.my_nodenum = interface.localNode.nodeNum  # in dec
        self.my_id = f"!{self.my_nodenum:08x}"

        self.init_complete = True
        logging.info(f'Connected to Meshtastic node as {self.my_id}')
        self.print_nodes()
        
        # Send an immediate node count report upon connection
        # We use a timer to delay slightly to ensure everything settles
        if get_env_bool('ENABLE_FEATURE_NODE_TOTALS', True):
            threading.Timer(10.0, self.report_node_count).start()

    def on_receive_text(self, packet: MeshPacket, interface):
        """Callback function triggered when a text message is received."""
        from_id = packet.get('fromId')
        text = packet.get('decoded', {}).get('text', '')
        logging.info(f"on_receive_text: Incoming text from {from_id}: {text}")

        to_id = packet['toId']

        if to_id == self.my_id:
            self.handle_private_message(packet)
        else:
            self.handle_public_message(packet)

    def handle_private_message(self, packet: MeshPacket):
        """Handle private messages."""
        message = packet['decoded']['text']
        from_id = packet['fromId']

        sender = self.node_db.get_by_id(from_id)
        logging.info(f"✉️  [PRIVATE MSG] '{message}' from {sender.long_name if sender else from_id}")

        words = message.split()
        command_name = words[0]
        command_instance = CommandFactory.create_command(command_name, self)
        if command_instance:
            self.command_logger.log_command(from_id, command_instance, message)
            
            def run_command():
                try:
                    logging.info(f"🤖 [BOT CMD] Running private command {command_name} in thread for {from_id}")
                    command_instance.handle_packet(packet)
                    logging.info(f"✅ [BOT CMD] Finished private command {command_name} for {from_id}")
                except Exception as e:
                    logging.error(f"❌ [BOT CMD] Error handling private command {command_name}: {e}", exc_info=True)
            
            threading.Thread(target=run_command, daemon=True).start()
        else:
            self.command_logger.log_unknown_request(from_id, message)

    def get_channel_name(self, packet: MeshPacket) -> str:
        """Get the name of the channel for a packet."""
        channel_index = packet.get('channel', 0)
        try:
            if self.interface and self.interface.localNode:
                channel = self.interface.localNode.channels[channel_index]
                if channel and channel.settings and channel.settings.name:
                    return channel.settings.name
        except (AttributeError, IndexError):
            pass
        return "Primary" if channel_index == 0 else f"Channel {channel_index}"

    def handle_public_message(self, packet: MeshPacket):
        """Handle public (group channel) messages."""
        message = packet['decoded']['text']
        from_id = packet['fromId']
        sender = self.node_db.get_by_id(from_id)
        sender_name = sender.long_name if sender else from_id
        channel_name = self.get_channel_name(packet)

        logging.info(f"📢 [GROUP MSG] Channel '{channel_name}' from {sender_name}: {message}")

        # Allow certain commands in public channels
        words = message.split()
        if words:
            command_name = words[0].lower()
            if command_name in ["!tr", "!ping", "!hello", "!nodes", "!status", "!whoami"]:
                env_var_name = f"ENABLE_COMMAND_{command_name.lstrip('!').upper()}"
                if get_env_bool(env_var_name, True):
                    logging.info(f"🤖 [BOT CMD] Received public {command_name} from {sender_name}")
                    command_instance = CommandFactory.create_command(command_name, self)
                    if command_instance:
                        def run_command():
                            try:
                                logging.info(f"🤖 [BOT CMD] Running public command {command_name} in thread for {from_id}")
                                # Commands by default reply via DM (reply_in_dm).
                                command_instance.handle_packet(packet)
                                logging.info(f"✅ [BOT CMD] Finished public command {command_name} for {from_id}")
                            except Exception as e:
                                logging.error(f"❌ [BOT CMD] Error handling public command {command_name}: {e}", exc_info=True)
                        
                        threading.Thread(target=run_command, daemon=True).start()
                        return # Stop processing responders

        responder = ResponderFactory.match_responder(message, self)
        if responder:
            try:
                outcome = responder.handle_packet(packet)

                if outcome:
                    logging.info(
                        f"🤖 [RESPONDER] Handled message from {sender.long_name if sender else from_id} with responder {responder.__class__.__name__}: {message}")
                    self.command_logger.log_responder_handled(from_id, responder, message)
            except (KeyError, ValueError) as e:
                logging.error(f"Packet format error handling message: {e}", exc_info=True)
            except Exception as e:
                logging.error(f"Error handling message: {e}", exc_info=True)

    def on_traceroute(self, packet, route):
        """Callback for when a traceroute response is received."""
        logging.info(f"on_traceroute: Received signal. Packet: {packet.get('id') if isinstance(packet, dict) else 'obj'}")
        def process_traceroute():
            try:
                target_id = packet.get('fromId')
                logging.info(f"on_traceroute: Processing response from {target_id} in thread. Route data type: {type(route)}")
                
                if target_id not in self.pending_traces:
                    logging.info(f"Received traceroute from {target_id} but no pending request found.")
                    return

                requesters = self.pending_traces.pop(target_id)
                if not isinstance(requesters, list):
                    requesters = [requesters]
                
                if route is None:
                    decoded_keys = packet.get('decoded', {}).keys()
                    logging.warning(f"Traceroute response from {target_id} contained no route data. Decoded keys: {list(decoded_keys)}")
                    for ctx in requesters:
                        # Handle both old (string) and new (tuple) formats during transition
                        r_id = ctx[0] if isinstance(ctx, tuple) else ctx
                        is_pub = ctx[1] if isinstance(ctx, tuple) else False
                        c_idx = ctx[3] if isinstance(ctx, tuple) else 0
                        
                        msg = f"Traceroute response received from {target_id}, but no route data was provided."
                        if is_pub:
                            self.interface.sendText(msg, destinationId=requesters[0][2] if isinstance(requesters[0], tuple) else "!all", channelIndex=c_idx, wantAck=True)
                        else:
                            self.interface.sendText(msg, destinationId=r_id, wantAck=True)
                    return

                def get_route_hops(r, key='route'):
                    if isinstance(r, dict):
                        return r.get(key, [])
                    return getattr(r, key, [])

                # Format compact routes
                target_node = self.node_db.get_by_id(target_id)
                t_name = target_node.short_name if target_node else target_id[-4:]
                
                my_node = self.node_db.get_by_id(self.my_id)
                m_name = my_node.short_name if my_node else self.my_id[-4:]

                # Outbound
                route_ids = get_route_hops(route, 'route')
                hops_to = []
                for nid in route_ids:
                    n = self.node_db.get_by_id(f"!{nid:08x}")
                    hops_to.append(n.short_name if n else f"{nid:08x}"[-4:])
                route_to_str = ">".join(hops_to) + (">" if hops_to else "") + t_name

                # Inbound
                route_back_ids = get_route_hops(route, 'route_back')
                hops_fr = []
                for nid in route_back_ids:
                    n = self.node_db.get_by_id(f"!{nid:08x}")
                    hops_fr.append(n.short_name if n else f"{nid:08x}"[-4:])
                route_fr_str = ">".join(hops_fr) + (">" if hops_fr else "") + m_name

                # Consolidate into a single message with hop counts
                combined_response = f"!tr {t_name}:\nTO({len(route_ids)}h): {route_to_str}\nFR({len(route_back_ids)}h): {route_fr_str}"

                # Longer wait for radio to settle after receiving the traceroute response
                time.sleep(8)

                for ctx in requesters:
                    if isinstance(ctx, tuple):
                        r_id, is_pub, to_id, c_idx = ctx
                        dest_id = to_id if is_pub else r_id
                    else:
                        dest_id = ctx # Fallback for old pending traces
                        is_pub = False
                        c_idx = 0

                    logging.info(f"Sending consolidated traceroute result to {dest_id} (Pub: {is_pub}):\n{combined_response}")
                    # Use wantAck=True for result delivery to ensure it gets through
                    self.interface.sendText(combined_response, destinationId=dest_id, channelIndex=c_idx, wantAck=True)
                    time.sleep(2)
                
                logging.info(f"Finished processing traceroute for {target_id}")
            except Exception as e:
                logging.error(f"Error in on_traceroute thread: {e}", exc_info=True)

        threading.Thread(target=process_traceroute, daemon=True).start()

    def on_receive(self, packet: MeshPacket, interface):
        from_id = packet.get('fromId')
        if from_id is None and 'from' in packet:
            from_id = f"!{packet['from']:08x}"

        portnum = packet.get('decoded', {}).get('portnum', 'unknown')
        logging.info(f"on_receive: Incoming packet from {from_id} (Port: {portnum})")
        
        if from_id == '!69828b98' or from_id == '!6985f59c':
            logging.info(f"Received ANY packet from {from_id}: {packet}")
            if portnum == 'ROUTING_APP':
                decoded = packet.get('decoded', {})
                logging.info(f"  ROUTING_APP Detail: requestId={decoded.get('requestId')}, routing={decoded.get('routing')}")

        # dump the packet to disk (if enabled)
        dump_packet(packet)

        for storage_api in self.storage_apis:
            try:
                storage_api.store_raw_packet(packet)
            except HTTPError as ex:
                logging.warning(f"Error storing packet: {ex.response.text}")
                pass
            except (ConnectionError, TimeoutError) as ex:
                logging.warning(f"Network error storing packet in API: {ex}")
                pass
            except Exception as ex:
                logging.warning(f"Unexpected error storing packet in API: {ex}", exc_info=True)
                pass

        sender = packet['fromId']
        node = self.node_db.get_by_id(sender)
        if not node:
            # logging.warning(f"Received packet from unknown sender {sender}")
            return

        if node:
            portnum = packet['decoded']['portnum'] if 'decoded' in packet else 'unknown'
            if sender == self.my_id and portnum == 'TELEMETRY_APP':
                # Ignore telemetry packets sent by self
                pass
            else:
                # Increment packets_today for this node
                self.node_info.node_packet_received(sender, portnum)

        if sender == self.my_id:
            recipient_id = packet['toId']
            recipient = self.node_db.get_by_id(recipient_id)
            portnum = packet['decoded']['portnum']

            logging.debug(
                f"Received packet from self: {recipient.long_name if recipient else recipient_id} (port {portnum})")

    def on_node_updated(self, node, interface):
        if interface.localNode and self.my_nodenum is None:
            self.my_nodenum = interface.localNode.nodeNum
            self.my_id = f"!{self.my_nodenum:08x}"

        # Check if the node is a new user
        if node['user'] is not None:
            mesh_node = MeshNode.from_dict(node)
            last_heard_int = node.get('lastHeard', 0)
            
            # Fix: Don't update if timestamp is 0 or older than what we have
            if last_heard_int > 0:
                last_heard = datetime.fromtimestamp(last_heard_int, tz=timezone.utc)
                existing_last_heard = self.node_info.get_last_heard(mesh_node.user.id)
                
                if not existing_last_heard or last_heard > existing_last_heard:
                    self.node_info.update_last_heard(mesh_node.user.id, last_heard)
            
            # Optimization: Only store and notify if the node has actually changed
            # or if it's the first time we've seen it.
            existing_user = self.node_db.get_by_id(mesh_node.user.id)
            is_new = existing_user is None
            has_changed = is_new or existing_user != mesh_node.user

            if has_changed:
                self.node_db.store_node(mesh_node)

                for storage_api in self.storage_apis:
                    try:
                        storage_api.store_node(mesh_node)
                    except HTTPError as ex:
                        logging.warning(f"Error storing node: {ex.response.text}")
                        pass
                    except (ConnectionError, TimeoutError) as ex:
                        logging.warning(f"Network error storing node: {ex}")
                        pass
                    except Exception as ex:
                        logging.warning(f"Unexpected error storing node: {ex}", exc_info=True)
                        pass

            if self.init_complete and is_new:
                current_last_heard = self.node_info.get_last_heard(mesh_node.user.id)
                last_heard_str = pretty_print_last_heard(current_last_heard) if current_last_heard else "unknown"
                logging.info(f"New user: {mesh_node.user.long_name} (last heard {last_heard_str})")

    def print_nodes(self):
        # filter nodes where last heard is more than 2 hours ago
        online_nodes = self.node_info.get_online_nodes()
        offline_nodes = self.node_info.get_offline_nodes()

        # print all nodes, sorted by last heard descending
        logging.info(f"Online nodes: ({len(online_nodes)})")
        sorted_nodes = sorted(online_nodes, key=lambda x: online_nodes[x], reverse=True)
        for node_id in sorted_nodes:
            if node_id == self.my_id:
                continue
            node = self.node_db.get_by_id(node_id)
            last_heard = self.node_info.get_last_heard(node_id)
            last_heard = pretty_print_last_heard(last_heard)
            encoded_name = safe_encode_node_name(node.long_name)
            logging.info(f"- {encoded_name} (last heard {last_heard})")

        logging.info(f"- Plus {len(offline_nodes)} offline nodes")

    def report_node_count(self, destination=None, channel_index=None):
        """Report the current node count to a specific channel or destination."""
        if not self.init_complete or not self.interface:
            logging.warning("Skipping node count report: interface not ready.")
            return

        if channel_index is None:
            channel_index = get_env_int('CHANNEL_FOR_NODE_TOTAL_BROADCAST', 2)

        online_nodes = self.node_info.get_online_nodes()
        count = len(online_nodes)

        if count == 0:
            message = "Warning MTEK cant see any nodes"
            self.last_report_zero = True
        else:
            message = f"MTEK has a node count of {count}"
            self.last_report_zero = False

        logging.info(f"Reporting node count: {message}")
        try:
            if destination:
                self.interface.sendText(message, destinationId=destination, wantAck=True)
            else:
                self.interface.sendText(message, channelIndex=channel_index, wantAck=True)
        except (OSError, ConnectionError) as e:
            logging.error(f"Network failure reporting node count: {e}", exc_info=True)
        except Exception as e:
            logging.error(f"Unexpected error reporting node count: {e}", exc_info=True)

    def check_for_zero_nodes(self):
        """Checks if the node count is zero and alerts immediately if it transitioned to zero."""
        if not self.init_complete or not self.interface:
            return

        online_nodes = self.node_info.get_online_nodes()
        count = len(online_nodes)

        if count == 0 and not self.last_report_zero:
            logging.warning("Immediate alert: Node count dropped to zero!")
            self.report_node_count()
        elif count > 0:
            # Reset flag so we can alert again if it drops to zero later
            self.last_report_zero = False

    def get_global_context(self):
        return {
            'nodes': self.node_db.list_nodes(),
            'online_nodes': self.node_info.get_online_nodes(),
            'offline_nodes': self.node_info.get_offline_nodes(),
        }

    def start_scheduler(self):
        schedule.every().day.at("00:00").do(self.node_info.reset_packets_today)
        if get_env_bool('ENABLE_FEATURE_NODE_TOTALS', True):
            report_frequency = get_env_int('FREQUENCY_OF_NODE_REPORTS', 3)
            schedule.every(report_frequency).hours.do(self.report_node_count)
            schedule.every(1).minutes.do(self.check_for_zero_nodes)
        while True:
            schedule.run_pending()
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                return

    def get_node_by_short_name(self, short_name: str) -> MeshNode.User | None:
        for node in self.node_db.list_nodes():
            if node.short_name.lower() == short_name.lower():
                return node
        return None
