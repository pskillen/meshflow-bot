import asyncio
import logging
import time
from collections import deque
import threading

class TcpProxy:
    def __init__(self, target_host, target_port=4403, listen_host='0.0.0.0', listen_port=4403, handshake_cache_size=100, rolling_cache_size=100):
        self.target_host = target_host
        self.target_port = int(target_port)
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        
        self.server = None
        self.target_reader = None
        self.target_writer = None
        
        self.clients = set()
        
        self.running = False
        self.loop = None
        self.thread = None
        
        self.handshake_packets = []
        self.handshake_max_count = handshake_cache_size 
        self.rolling_packets = deque(maxlen=rolling_cache_size)
        
        self.last_target_activity = time.time()
        self.reconnecting = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self._stop_loop)

    def _stop_loop(self):
        if self.server:
            self.server.close()
        for writer in self.clients:
            try: writer.close()
            except: pass
        if self.target_writer:
            try: self.target_writer.close()
            except: pass

    def get_status(self):
        if not self.running:
            return "Proxy: Offline"
        
        silence = time.time() - self.last_target_activity
        client_count = len(self.clients)
        cached_count = len(self.handshake_packets) + len(self.rolling_packets)
            
        state = "Reconnecting" if self.reconnecting else ("Online" if self.target_writer else "Offline")
        
        return {
            "state": state,
            "connected": self.target_writer is not None and not self.reconnecting,
            "clients": client_count,
            "silence_secs": int(silence),
            "cached_packets": cached_count
        }

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._async_run())

    async def _async_run(self):
        logging.info(f"Starting TCP Proxy on {self.listen_host}:{self.listen_port} -> {self.target_host}:{self.target_port}")
        
        try:
            self.server = await asyncio.start_server(
                self._handle_client, self.listen_host, self.listen_port)
        except Exception as e:
            logging.error(f"Failed to bind proxy port {self.listen_port}: {e}")
            self.running = False
            return

        asyncio.create_task(self._target_connection_manager())
        asyncio.create_task(self._watchdog())

        try:
            async with self.server:
                while self.running:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self._stop_loop()

    async def _watchdog(self):
        last_heartbeat_log = time.time()
        while self.running:
            current_time = time.time()
            if self.target_writer and not self.reconnecting:
                if current_time - self.last_target_activity > 300.0:
                    logging.warning(f"Watchdog: No data from radio for 300s. Forcing reconnect...")
                    try: self.target_writer.close()
                    except: pass
                    self.target_reader = None
                    self.target_writer = None

            if current_time - last_heartbeat_log > 60.0:
                client_count = len(self.clients)
                status = "Connected" if self.target_writer and not self.reconnecting else "RECONNECTING"
                silence = current_time - self.last_target_activity
                logging.info(f"Proxy Heartbeat: {status}. Last radio data {silence:.1f}s ago. Clients: {client_count}")
                last_heartbeat_log = current_time
            
            await asyncio.sleep(5)

    async def _target_connection_manager(self):
        backoff_time = 5.0
        max_backoff_time = 60.0
        backoff_rate = 2.0
        
        while self.running:
            if self.target_writer is None or self.target_reader is None:
                self.reconnecting = True
                self._disconnect_all_clients()
                self.handshake_packets.clear()
                self.rolling_packets.clear()

                try:
                    logging.info(f"Proxy attempting to connect to target device at {self.target_host}:{self.target_port}...")
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(self.target_host, self.target_port),
                        timeout=5.0
                    )
                    self.target_reader = reader
                    self.target_writer = writer
                    self.last_target_activity = time.time()
                    self.reconnecting = False
                    backoff_time = 5.0 # Reset backoff on success
                    logging.info(f"Proxy successfully connected to target device at {self.target_host}:{self.target_port}")
                    asyncio.create_task(self._read_from_target())
                except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                    logging.error(f"Failed to connect to target ({self.target_host}): {e}. Retrying in {backoff_time:.1f}s...")
                    await asyncio.sleep(backoff_time)
                    backoff_time = min(backoff_time * backoff_rate, max_backoff_time)
                except Exception as e:
                    logging.error(f"Unexpected error in target connection manager: {e}", exc_info=True)
                    await asyncio.sleep(backoff_time)
                    backoff_time = min(backoff_time * backoff_rate, max_backoff_time)
            else:
                await asyncio.sleep(1)

    def _disconnect_all_clients(self):
        for writer in list(self.clients):
            try: writer.close()
            except: pass
        self.clients.clear()
        logging.info("Disconnected all proxy clients to force re-sync.")

    async def _read_from_target(self):
        reader = self.target_reader
        writer = self.target_writer
        
        in_buffer = b''
        while self.running and self.target_reader == reader:
            try:
                data = await reader.read(16384)
                if not data:
                    logging.warning("Radio closed connection. Triggering re-sync...")
                    break
                self.last_target_activity = time.time()
                
                in_buffer += data
                
                while len(in_buffer) >= 4:
                    if in_buffer[0:2] != b'\x94\xc3':
                        idx = in_buffer.find(b'\x94\xc3')
                        if idx == -1:
                            in_buffer = b''
                            break
                        in_buffer = in_buffer[idx:]
                        continue
                    
                    length = (in_buffer[2] << 8) | in_buffer[3]
                    total_len = length + 4
                    
                    if len(in_buffer) < total_len:
                        break
                    
                    packet = in_buffer[:total_len]
                    in_buffer = in_buffer[total_len:]
                    
                    if len(self.handshake_packets) < self.handshake_max_count:
                        self.handshake_packets.append(packet)
                    self.rolling_packets.append(packet)
                    
                    for client_writer in list(self.clients):
                        try:
                            client_writer.write(packet)
                            await client_writer.drain()
                        except Exception as e:
                            logging.debug(f"Failed to forward packet to client: {e}")
                            self._remove_client(client_writer)
            except Exception as e:
                logging.error(f"Error reading from radio: {e}")
                break
        
        if self.target_writer == writer:
            try: writer.close()
            except: pass
            self.target_writer = None
            self.target_reader = None

    async def _handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        logging.info(f"+++ PROXY: New connection accepted from {addr}")
        self.clients.add(writer)
        
        h_snapshot = list(self.handshake_packets)
        r_snapshot = list(self.rolling_packets)
        
        if addr[0] not in ('127.0.0.1', 'localhost'):
            try:
                await asyncio.sleep(2.0)
                for p in h_snapshot:
                    writer.write(p)
                    await writer.drain()
                    await asyncio.sleep(0.05)
                for p in r_snapshot:
                    writer.write(p)
                    await writer.drain()
                    await asyncio.sleep(0.01)
                logging.info(f"Replayed {len(h_snapshot) + len(r_snapshot)} packets to {addr}")
            except Exception as e:
                self._remove_client(writer)
                return

        while self.running:
            try:
                data = await reader.read(16384)
                if not data:
                    break
                if self.target_writer and not self.reconnecting:
                    try:
                        self.target_writer.write(data)
                        await self.target_writer.drain()
                    except Exception as e:
                        logging.error(f"Error sending to radio: {e}")
                        try: self.target_writer.close()
                        except: pass
                        self.target_writer = None
            except Exception as e:
                logging.debug(f"Error receiving from client: {e}")
                break
                
        self._remove_client(writer)

    def _remove_client(self, writer):
        addr = None
        try:
            addr = writer.get_extra_info('peername')
            logging.info(f"--- PROXY: Removing client {addr}")
        except:
            logging.info("--- PROXY: Removing unknown client")
            
        if writer in self.clients:
            self.clients.remove(writer)
        try: writer.close()
        except: pass
