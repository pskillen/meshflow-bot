import socket
import select
import threading
import logging
import time
from collections import deque

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
        self.running = False
        
        # We now store full packets instead of raw bytes to ensure stream integrity
        self.handshake_packets = []
        self.handshake_max_count = 20 # First 20 packets are usually the config sync
        
        # Rolling history of last 100 packets
        self.rolling_packets = deque(maxlen=100)
        
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
        return {
            "connected": self.target_socket is not None and self.target_socket.fileno() != -1,
            "clients": len(self.clients),
            "silence_secs": int(silence),
            "cached_packets": len(self.handshake_packets) + len(self.rolling_packets)
        }

    def _connect_to_target(self):
        """Internal helper to connect and reset buffers"""
        backoff = 1
        while self.running:
            try:
                # Reset buffers on new connection to ensure we capture fresh handshake
                self.handshake_packets = []
                self.rolling_packets.clear()
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
                # Out of sync, find next magic header
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
                # Need more data for a full packet
                break
            
            # Extract full packet
            packet = self.in_buffer[:total_len]
            self.in_buffer = self.in_buffer[total_len:]
            
            # Update cache
            if len(self.handshake_packets) < self.handshake_max_count:
                self.handshake_packets.append(packet)
            else:
                self.rolling_packets.append(packet)
            
            # Broadcast to all clients
            for client in self.clients[:]:
                try:
                    client.sendall(packet)
                except:
                    if client in self.clients: self.clients.remove(client)
                    try: client.close()
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
                inputs = [self.server_socket, self.target_socket]
                current_inputs = [s for s in inputs + self.clients if s and s.fileno() != -1]
                readable, _, _ = select.select(current_inputs, [], [], 1.0)
            except Exception as e:
                logging.error(f"Select error: {e}")
                self.clients = [c for c in self.clients if c.fileno() != -1]
                continue

            current_time = time.time()

            if current_time - last_heartbeat_log > 60.0:
                silence_duration = current_time - self.last_target_activity
                logging.info(f"Proxy Heartbeat: Connected. Last data from radio {silence_duration:.1f}s ago. Clients: {len(self.clients)}")
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
                        self.clients.append(client_socket)
                        
                        # Replay full packets with pacing
                        def replay(target_sock, packets_to_send, client_addr):
                            try:
                                for i, p in enumerate(packets_to_send):
                                    target_sock.sendall(p)
                                    # Pacing: 50ms for first few handshake packets, 10ms for history
                                    time.sleep(0.05 if i < 10 else 0.01)
                                logging.info(f"Replayed {len(packets_to_send)} full packets to {client_addr}")
                            except Exception as e:
                                logging.debug(f"Client {client_addr} disconnected during replay: {e}")

                        all_packets = self.handshake_packets + list(self.rolling_packets)
                        if all_packets:
                            threading.Thread(target=replay, args=(client_socket, all_packets, addr), daemon=True).start()
                                
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
                            if sock in self.clients: self.clients.remove(sock)
                            sock.close()
                        else:
                            try:
                                self.target_socket.sendall(data)
                            except Exception as e:
                                logging.error(f"Error sending to target: {e}")
                                self.target_socket.close()
                                self._connect_to_target()
                    except:
                        if sock in self.clients: self.clients.remove(sock)
                        try: sock.close()
                        except: pass

                else:
                    # Data from a client
                    try:
                        data = sock.recv(16384)
                        if not data:
                            if sock in self.clients:
                                self.clients.remove(sock)
                            sock.close()
                        else:
                            # Forward to target
                            try:
                                self.target_socket.sendall(data)
                            except Exception as e:
                                logging.error(f"Error sending to target: {e}. Attempting to reconnect...")
                                try:
                                    self.target_socket.close()
                                except:
                                    pass
                                
                                reconnected = False
                                backoff = 1
                                while self.running and not reconnected:
                                    try:
                                        self.target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                        self.target_socket.connect((self.target_host, self.target_port))
                                        logging.info("Reconnected to target successfully.")
                                        self.target_socket.sendall(data)
                                        reconnected = True
                                    except Exception as ex:
                                        logging.error(f"Reconnect failed: {ex}. Retrying in {backoff}s...")
                                        time.sleep(backoff)
                                        backoff = min(backoff * 2, 10)
                                
                                if not reconnected:
                                    self.running = False
                    except:
                        if sock in self.clients:
                            self.clients.remove(sock)
                        try:
                            sock.close()
                        except:
                            pass

        # Cleanup
        if self.server_socket: 
            try: self.server_socket.close()
            except: pass
        if self.target_socket: 
            try: self.target_socket.close()
            except: pass
        for c in self.clients: 
            try: c.close()
            except: pass
