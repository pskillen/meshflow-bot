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
        
        # Buffer for the initial handshake/config (captured at start of radio connection)
        self.handshake_buffer = b''
        self.handshake_max = 16384  # 16KB is plenty for the initial protobuf sync
        
        # Rolling buffer for recent data (last 256KB for history)
        self.rolling_buffer = deque(maxlen=262144)
        
        self.last_target_activity = time.time()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        if self.target_socket:
            try:
                self.target_socket.close()
            except:
                pass

    def get_status(self):
        if not self.running:
            return "Proxy: Offline"
        
        silence = time.time() - self.last_target_activity
        return {
            "connected": self.target_socket is not None and self.target_socket.fileno() != -1,
            "clients": len(self.clients),
            "silence_secs": int(silence),
            "cached_kb": (len(self.handshake_buffer) + len(self.rolling_buffer)) // 1024
        }

    def _connect_to_target(self):
        """Internal helper to connect and reset buffers"""
        backoff = 1
        while self.running:
            try:
                # Reset buffers on new connection to ensure we capture fresh handshake
                self.handshake_buffer = b''
                self.rolling_buffer.clear()
                
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
                        
                        # Replay buffers with pacing
                        def replay():
                            try:
                                # 1. Handshake (essential config)
                                if self.handshake_buffer:
                                    client_socket.sendall(self.handshake_buffer)
                                    time.sleep(0.1) # Small pause
                                
                                # 2. Rolling history in chunks
                                if self.rolling_buffer:
                                    rolling_data = bytes(self.rolling_buffer)
                                    chunk_size = 4096
                                    for i in range(0, len(rolling_data), chunk_size):
                                        client_socket.sendall(rolling_data[i:i+chunk_size])
                                        time.sleep(0.01) # 10ms pacing between chunks
                                    logging.info(f"Replayed {len(self.handshake_buffer)}b handshake and {len(rolling_data)}b history to {addr}")
                            except Exception as e:
                                logging.debug(f"Client {addr} disconnected during replay: {e}")

                        threading.Thread(target=replay, daemon=True).start()
                                
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
                        
                        if len(self.handshake_buffer) < self.handshake_max:
                            to_add = data[:self.handshake_max - len(self.handshake_buffer)]
                            self.handshake_buffer += to_add
                        
                        self.rolling_buffer.extend(data)

                        for client in self.clients[:]:
                            try:
                                client.sendall(data)
                            except:
                                if client in self.clients: self.clients.remove(client)
                                try: client.close()
                                except: pass
                    except Exception as e:
                        logging.error(f"Error reading from target: {e}")
                        self.target_socket.close()
                        time.sleep(2)
                        self._connect_to_target()

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
