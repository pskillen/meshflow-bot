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
        
        # Increased handshake cache to ensure full config is captured
        self.handshake_packets = []
        self.handshake_max_count = 40 
        
        # Rolling history of last 50 packets
        self.rolling_packets = deque(maxlen=50)
        
        # Buffer for incoming raw bytes from the radio
        self.in_buffer = b''
        
        self.last_target_activity = time.time()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
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
            
        return {
            "connected": self.target_socket is not None and self.target_socket.fileno() != -1,
            "clients": client_count,
            "silence_secs": int(silence),
            "cached_packets": len(self.handshake_packets) + len(self.rolling_packets)
        }

    def _connect_to_target(self):
        """Internal helper to connect to radio"""
        backoff = 1
        while self.running:
            try:
                # We NO LONGER clear handshake/rolling buffers here 
                # so that a radio reboot doesn't break client history.
                self.in_buffer = b''
                
                self.target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.target_socket.connect((self.target_host, self.target_port))
                logging.info(f"Proxy connected to target device at {self.target_host}:{self.target_port}")
                self.last_target_activity = time.time()
                return True
            except Exception as e:
                logging.error(f"Failed to connect to target ({self.target_host}): {e}. Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
        return False

    def _process_radio_data(self, data):
        """Frames raw bytes into Meshtastic packets and caches them"""
        self.in_buffer += data
        
        while len(self.in_buffer) >= 4:
            # Check for magic header
            if self.in_buffer[0:2] != b'\x94\xc3':
                idx = self.in_buffer.find(b'\x94\xc3')
                if idx == -1:
                    self.in_buffer = b''
                    break
                self.in_buffer = self.in_buffer[idx:]
                continue
            
            # Read length (big-endian)
            length = (self.in_buffer[2] << 8) | self.in_buffer[3]
            total_len = length + 4
            
            if len(self.in_buffer) < total_len:
                break
            
            # Extract full packet
            packet = self.in_buffer[:total_len]
            self.in_buffer = self.in_buffer[total_len:]
            
            # Update cache
            if len(self.handshake_packets) < self.handshake_max_count:
                self.handshake_packets.append(packet)
            else:
                self.rolling_packets.append(packet)
            
            # Broadcast to all clients immediately
            with self.clients_lock:
                for client_sock in self.clients[:]:
                    try:
                        client_sock.sendall(packet)
                    except:
                        self._remove_client(client_sock)

    def _remove_client(self, sock):
        with self.clients_lock:
            if sock in self.clients:
                self.clients.remove(sock)
        try: sock.close()
        except: pass

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

        if not self._connect_to_target():
            return

        watchdog_timeout = 300.0
        last_heartbeat_log = time.time()

        while self.running:
            try:
                with self.clients_lock:
                    client_socks = [s for s in self.clients if s.fileno() != -1]
                
                inputs = [self.server_socket, self.target_socket] + client_socks
                readable, _, _ = select.select(inputs, [], [], 1.0)
            except Exception as e:
                logging.error(f"Select error: {e}")
                continue

            current_time = time.time()

            if current_time - last_heartbeat_log > 60.0:
                with self.clients_lock:
                    client_count = len(self.clients)
                logging.info(f"Proxy Heartbeat: Connected. Last data from radio {current_time - self.last_target_activity:.1f}s ago. Clients: {client_count}")
                last_heartbeat_log = current_time
            
            if current_time - self.last_target_activity > watchdog_timeout:
                logging.warning(f"Watchdog: No data from radio for {watchdog_timeout}s. Forcing reconnect...")
                try: self.target_socket.close()
                except: pass
                self._connect_to_target()

            for sock in readable:
                if sock is self.server_socket:
                    try:
                        client_socket, addr = self.server_socket.accept()
                        logging.info(f"New proxy connection from {addr}")
                        
                        with self.clients_lock:
                            self.clients.append(client_socket)
                        
                        # Replay full packets with pacing in a thread
                        def replay(target_sock, handshake, history, client_addr):
                            try:
                                # Replay handshake first
                                for p in handshake:
                                    target_sock.sendall(p)
                                    time.sleep(0.02)
                                
                                # Replay recent history
                                for p in history:
                                    target_sock.sendall(p)
                                    time.sleep(0.01)
                                    
                                logging.info(f"Replayed {len(handshake) + len(history)} packets to {client_addr}")
                            except Exception as e:
                                logging.debug(f"Client {client_addr} disconnected during replay: {e}")
                                self._remove_client(target_sock)

                        h_snapshot = list(self.handshake_packets)
                        r_snapshot = list(self.rolling_packets)
                        threading.Thread(target=replay, args=(client_socket, h_snapshot, r_snapshot, addr), daemon=True).start()
                                
                    except Exception as e:
                         logging.error(f"Error accepting connection: {e}")

                elif sock is self.target_socket:
                    self.last_target_activity = time.time()
                    try:
                        data = self.target_socket.recv(16384)
                        if not data:
                            logging.warning("Target closed connection. Reconnecting...")
                            self.target_socket.close()
                            self._connect_to_target()
                            break
                        
                        self._process_radio_data(data)
                        
                    except Exception as e:
                        logging.error(f"Error reading from target: {e}")
                        self.target_socket.close()
                        time.sleep(2)
                        self._connect_to_target()

                else:
                    # Data from a client forwarded to target
                    try:
                        data = sock.recv(16384)
                        if not data:
                            self._remove_client(sock)
                        else:
                            try:
                                self.target_socket.sendall(data)
                            except Exception as e:
                                logging.error(f"Error sending to target: {e}")
                                self.target_socket.close()
                                self._connect_to_target()
                    except:
                        self._remove_client(sock)

        # Cleanup
        if self.server_socket: 
            try: self.server_socket.close()
            except: pass
        if self.target_socket: 
            try: self.target_socket.close()
            except: pass
        with self.clients_lock:
            for c_sock in self.clients: 
                try: c_sock.close()
                except: pass
