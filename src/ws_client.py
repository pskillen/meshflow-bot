"""
WebSocket client for receiving commands from the Meshflow API.

Connects to ws/nodes/?api_key=<token> and invokes callbacks when commands
(e.g. traceroute) are received.
"""

import asyncio
import json
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class MeshflowWSClient:
    """
    WebSocket client that connects to the Meshflow API node command endpoint.

    Runs in a background thread and invokes callbacks for received commands.
    Reconnects with exponential backoff on disconnect.
    """

    def __init__(
        self,
        ws_url: str,
        api_key: str,
        on_traceroute: Callable[[int], None],
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            ws_url: Base WebSocket URL (e.g. ws://localhost:8000)
            api_key: NodeAPIKey for authentication
            on_traceroute: Callback(target_node_id: int) when traceroute command received
            on_connect: Optional callback when connected
            on_disconnect: Optional callback when disconnected
        """
        self.ws_url = ws_url.rstrip("/")
        self.api_key = api_key
        self.on_traceroute = on_traceroute
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._backoff = 1.0  # Reset on successful connect so reconnects start fast

    def _get_ws_endpoint(self) -> str:
        return f"{self.ws_url}/ws/nodes/?api_key={self.api_key}"

    def start(self):
        """Start the WebSocket client in a background thread."""
        if self._running:
            return
        self._running = True
        import threading

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run())
            finally:
                self._loop.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        logger.info("MeshflowWSClient: started")

    def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        if self._loop and self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)

    async def _run(self):
        """Main loop with reconnection."""
        backoff = 1.0
        max_backoff = 300.0

        while self._running:
            try:
                await self._connect_and_receive()
            except asyncio.CancelledError:
                logger.info("MeshflowWSClient: stopped")
                break
            except Exception as e:
                logger.warning(
                    f"MeshflowWSClient: connection lost ({type(e).__name__}: {e}). "
                    f"Reconnecting in {backoff:.0f}s..."
                )
                if self.on_disconnect:
                    try:
                        self.on_disconnect()
                    except Exception:
                        pass

            if not self._running:
                break

            await asyncio.sleep(backoff)
            backoff = getattr(self, "_backoff", backoff)  # Use reset value from successful connect
            backoff = min(backoff * 1.5, max_backoff)

        logger.info("MeshflowWSClient: run loop ended")

    async def _connect_and_receive(self):
        """Connect to WebSocket and receive messages until disconnect."""
        try:
            import websockets
            from websockets.exceptions import ConnectionClosed
        except ImportError:
            raise ImportError("websockets package required. Install with: pip install websockets")

        endpoint = self._get_ws_endpoint()
        # Django Channels AllowedHostsOriginValidator requires Origin header.
        # Derive from ws_url (e.g. ws://localhost:8000 -> http://localhost:8000)
        origin = self.ws_url.replace("ws://", "http://").replace("wss://", "https://")
        async with websockets.connect(
            endpoint,
            origin=origin,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            self._backoff = 1.0  # Reset so next reconnect starts with short delay
            logger.info("MeshflowWSClient: connected")
            if self.on_connect:
                try:
                    self.on_connect()
                except Exception as e:
                    logger.warning(f"MeshflowWSClient: on_connect error: {e}")

            while self._running:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                except asyncio.TimeoutError:
                    continue
                except ConnectionClosed as e:
                    code = getattr(getattr(e, "rcvd", None), "code", None)
                    logger.info(f"MeshflowWSClient: connection closed by server (code={code})")
                    raise

                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    logger.warning(f"MeshflowWSClient: invalid JSON: {msg[:100]}")
                    continue

                cmd_type = data.get("type")
                if cmd_type == "traceroute":
                    target = data.get("target")
                    if target is not None:
                        try:
                            target_id = int(target)
                            logger.info(f"MeshflowWSClient: received traceroute command, target={target_id}")
                            # Run in thread so a blocking/long-running TR doesn't block receiving
                            # further commands (e.g. multiple TRs in quick succession, or TR that never returns)
                            task = asyncio.create_task(asyncio.to_thread(self.on_traceroute, target_id))

                            def _task_done(t):
                                if t.cancelled():
                                    return
                                exc = t.exception()
                                if exc:
                                    logger.warning(f"MeshflowWSClient: traceroute task failed: {exc}")

                            task.add_done_callback(_task_done)
                        except (TypeError, ValueError):
                            logger.warning(f"MeshflowWSClient: invalid traceroute target: {target}")
                    else:
                        logger.warning("MeshflowWSClient: traceroute command missing target")
                else:
                    logger.debug(f"MeshflowWSClient: ignored command type: {cmd_type}")
