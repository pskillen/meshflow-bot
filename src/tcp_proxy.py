import socket
import select
import threading
import logging
import time
from collections import deque

class TcpProxy:
    def __init__(self, target_host, target_port=4403, listen_host='0.0.0.0', listen_port=4403):
        self.target_host = target_host
        self.target_port = int(target_port)
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.server_socket = None
        self.target_socket = None
        
        self.clients = []
        self.clients_lock = threading.Lock()
        
        self.running = False
        
        # Handshake: The first 50 packets from a fresh radio connection
        self.handshake_packets = []
        self.handshake_max_count = 50 
        
        # History: The last 50 packets seen
        self.rolling_packets = deque(maxlen=50)
        
        # Buffer for incoming raw bytes from the radio
        self.in_buffer = b''
        
        self.last_target_activity = time.time()
        self.reconnecting = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        self._disconnect_all_clients()
        if self.server_socket:
            try: self.server_socket.close()
            except: pass
        if self.target_socket:
            try: self.target_socket.close()
            except: pass

    def get_status(self):
        if not self.running:
            return "Proxy: Offline"
        
        silence = time.time() - self.last_target_activity
        with self.clients_lock:
            client_count = len(self.clients)
            
        state = "Reconnecting" if self.reconnecting else ("Online" if self.target_socket else "Offline")
        
        return {
            "state": state,
            "connected": self.target_socket is not None and not self.reconnecting,
            "clients": client_count,
            "silence_secs": int(silence),
            "cached_packets": len(self.handshake_packets) + len(self.rolling_packets)
        }

    def _disconnect_all_clients(self):
        """Force all clients to disconnect so they can re-sync with a new radio session"""
        with self.clients_lock:
            for sock in self.clients:
                try: sock.close()
                except: pass
            self.clients = []
        logging.info("Disconnected all proxy clients to force re-sync.")

    def _connect_to_target(self):
        """Helper to connect to radio with Keep-Alives (Non-blocking retry)"""
        # Clear state for new connection
        self.handshake_packets = [] 
        self.in_buffer = b''
        self._disconnect_all_clients()
        self.reconnecting = True

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0) # 5s timeout for connection attempt
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            except: pass

            sock.connect((self.target_host, self.target_port))
            sock.settimeout(None) # Reset to blocking for select()
            self.target_socket = sock
            self.last_target_activity = time.time()
            self.reconnecting = False
            logging.info(f"Proxy connected to target device at {self.target_host}:{self.target_port}")
            return True
        except Exception as e:
            logging.error(f"Failed to connect to target ({self.target_host}): {e}")
            self.target_socket = None
            return False

    def _process_radio_data(self, data):
        """Frames raw bytes into Meshtastic packets and caches them"""
        self.in_buffer += data
        
        while len(self.in_buffer) >= 4:
            if self.in_buffer[0:2] != b'\x94\xc3':
                idx = self.in_buffer.find(b'\x94\xc3')
                if idx == -1:
                    self.in_buffer = b''
                    break
                self.in_buffer = self.in_buffer[idx:]
                continue
            
            length = (self.in_buffer[2] << 8) | self.in_buffer[3]
            total_len = length + 4
            
            if len(self.in_buffer) < total_len:
                break
            
            packet = self.in_buffer[:total_len]
            self.in_buffer = self.in_buffer[total_len:]
            
            if len(self.handshake_packets) < self.handshake_max_count:
                self.handshake_packets.append(packet)
            self.rolling_packets.append(packet)
            
            with self.clients_lock:
                for client_sock in self.clients[:]:
                    try:
                        client_sock.sendall(packet)
                    except:
                        self._remove_client(client_sock)

    def _remove_client(self, sock):
        try:
            addr = sock.getpeername()
            logging.info(f"--- PROXY: Removing client {addr}")
        except:
            logging.info("--- PROXY: Removing unknown client")

        with self.clients_lock:
            if sock in self.clients:
                self.clients.remove(sock)
        try: sock.close()
        except: pass
        
        with self.clients_lock:
            logging.info(f"--- PROXY: Remaining clients: {len(self.clients)}")

    def _run(self):
        logging.info(f"Starting TCP Proxy on {self.listen_host}:{self.listen_port} -> {self.target_host}:{self.target_port}")

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.listen_host, self.listen_port))
        except Exception as e:
            logging.error(f"Failed to bind proxy port {self.listen_port}: {e}")
            self.running = False
            return
            
        self.server_socket.listen(5)

        last_heartbeat_log = time.time()
        last_reconnect_attempt = 0
        watchdog_timeout = 300.0

        while self.running:
            current_time = time.time()

            # Reconnection logic (non-blocking)
            if not self.target_socket or self.reconnecting:
                if current_time - last_reconnect_attempt > 10.0:
                    last_reconnect_attempt = current_time
                    self._connect_to_target()
                
                # Sleep a bit to not peg CPU while radio is down
                if not self.target_socket:
                    time.sleep(1.0)

            try:
                with self.clients_lock:
                    client_socks = [s for s in self.clients if s.fileno() != -1]
                
                inputs = [self.server_socket] + client_socks
                if self.target_socket and not self.reconnecting:
                    inputs.append(self.target_socket)
                
                readable, _, _ = select.select(inputs, [], [], 1.0)
            except Exception as e:
                logging.error(f"Select error: {e}")
                time.sleep(0.5)
                continue

            # Heartbeat Logging
            if current_time - last_heartbeat_log > 60.0:
                with self.clients_lock:
                    client_count = len(self.clients)
                    client_info = []
                    for s in self.clients:
                        try:
                            peer = s.getpeername()
                            client_info.append(f"{peer[0]}:{peer[1]}")
                        except:
                            client_info.append("unknown")
                
                status = "Connected" if self.target_socket and not self.reconnecting else "RECONNECTING"
                silence = current_time - self.last_target_activity
                logging.info(f"Proxy Heartbeat: {status}. Last radio data {silence:.1f}s ago. Clients: {client_count} ({', '.join(client_info)})")
                last_heartbeat_log = current_time
            
            # Watchdog: Force reconnect if silence is too long on an "active" connection
            if self.target_socket and not self.reconnecting:
                if current_time - self.last_target_activity > watchdog_timeout:
                    logging.warning(f"Watchdog: No data from radio for {watchdog_timeout}s. Forcing reconnect...")
                    try: self.target_socket.close()
                    except: pass
                    self.target_socket = None # Trigger reconnect logic

            for sock in readable:
                if sock is self.server_socket:
                    try:
                        client_socket, addr = self.server_socket.accept()
                        logging.info(f"+++ PROXY: New connection accepted from {addr}")
                        
                        with self.clients_lock:
                            self.clients.append(client_socket)
                            logging.info(f"--- PROXY: Total active clients now: {len(self.clients)}")
                        
                        def replay(target_sock, handshake, history, client_addr):
                            if client_addr[0] in ('127.0.0.1', 'localhost'):
                                return
                            try:
                                time.sleep(2.0)
                                for p in handshake:
                                    target_sock.sendall(p)
                                    time.sleep(0.05) 
                                for p in history:
                                    target_sock.sendall(p)
                                    time.sleep(0.01)
                                logging.info(f"Replayed {len(handshake) + len(history)} packets to {client_addr}")
                            except Exception as e:
                                self._remove_client(target_sock)

                        h_snapshot = list(self.handshake_packets)
                        r_snapshot = list(self.rolling_packets)
                        threading.Thread(target=replay, args=(client_socket, h_snapshot, r_snapshot, addr), daemon=True).start()
                                
                    except Exception as e:
                         logging.error(f"Error accepting connection: {e}")

                elif self.target_socket and sock is self.target_socket:
                    self.last_target_activity = time.time()
                    try:
                        data = self.target_socket.recv(16384)
                        if not data:
                            logging.warning("Radio closed connection. Triggering re-sync...")
                            self.target_socket.close()
                            self.target_socket = None
                            break
                        self._process_radio_data(data)
                    except Exception as e:
                        logging.error(f"Error reading from radio: {e}")
                        self.target_socket.close()
                        self.target_socket = None

                else:
                    # Data from a client forwarded to radio
                    try:
                        data = sock.recv(16384)
                        if not data:
                            self._remove_client(sock)
                        elif self.target_socket and not self.reconnecting:
                            try:
                                chunk_size = 512
                                for i in range(0, len(data), chunk_size):
                                    self.target_socket.sendall(data[i:i+chunk_size])
                                    time.sleep(0.01) 
                            except Exception as e:
                                logging.error(f"Error sending to radio: {e}")
                                self.target_socket.close()
                                self.target_socket = None
                    except:
                        self._remove_client(sock)

        self.stop()
