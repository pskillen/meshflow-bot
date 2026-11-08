"""
WebSocket client for receiving commands from the Meshflow API.

Connects to ws/nodes/?api_key=<token> and invokes callbacks when commands
(e.g. traceroute) are received.
"""

import asyncio
import json
import logging
import time
from typing import Callable, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
BACKOFF_FACTOR = 2.0
# A connection that stayed up this long counts as good even if it never got a
# message, so a server that accepts and then drops us can't pin us at 1s retries.
STABLE_CONNECTION_SECONDS = 30.0


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
        on_apply_mc_channel_config: Optional[Callable[[list], None]] = None,
        on_refresh_feeder_config: Optional[Callable[[], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        feeder_pubkey_prefix_provider: Optional[Callable[[], Optional[str]]] = None,
        feeder_node_id_provider: Optional[Callable[[], Optional[int]]] = None,
        feeder_scoped_provider: Optional[Callable[[], bool]] = None,
    ):
        """
        Args:
            ws_url: Base WebSocket URL (e.g. ws://localhost:8000)
            api_key: NodeAPIKey for authentication
            on_traceroute: Callback(target_node_id: int) when traceroute command received
            on_connect: Optional callback when connected
            on_disconnect: Optional callback when disconnected
            feeder_scoped_provider: Returns True when the primary storage API
                uses the v4 feeder URLs; the endpoint then carries
                ``feeder_scoped=1`` and no ``feeder_node_id``.
        """
        self.ws_url = ws_url.rstrip("/")
        self.api_key = api_key
        self.on_traceroute = on_traceroute
        self.on_apply_mc_channel_config = on_apply_mc_channel_config
        self.on_refresh_feeder_config = on_refresh_feeder_config
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self._feeder_pubkey_prefix_provider = feeder_pubkey_prefix_provider
        self._feeder_node_id_provider = feeder_node_id_provider
        self._feeder_scoped_provider = feeder_scoped_provider

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None  # live connection, for reconnect()
        self._backoff = INITIAL_BACKOFF_SECONDS  # delay before the next reconnect

    def _get_ws_endpoint(self) -> str:
        url = f"{self.ws_url}/ws/nodes/?api_key={self.api_key}"
        if self._feeder_pubkey_prefix_provider:
            prefix = self._feeder_pubkey_prefix_provider()
            if prefix:
                url += f"&feeder_pubkey_prefix={quote(prefix, safe='')}"
        if self._feeder_scoped_provider and self._feeder_scoped_provider():
            return url + "&feeder_scoped=1"
        if self._feeder_node_id_provider:
            node_id = self._feeder_node_id_provider()
            if node_id is not None:
                url += f"&feeder_node_id={quote(str(node_id), safe='')}"
        return url

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

    def reconnect(self):
        """Drop the live connection so the run loop reconnects with a freshly
        built endpoint (e.g. after the feeder's node number changed). A no-op
        when not started; if a connect attempt is pending it already rebuilds
        the endpoint."""
        ws, loop = self._ws, self._loop
        if not self._running or ws is None or loop is None:
            return
        logger.info("MeshflowWSClient: reconnecting to pick up changed feeder identity")
        asyncio.run_coroutine_threadsafe(ws.close(), loop)

    def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        if self._loop and self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)

    async def _run(self):
        """Main loop with reconnection."""
        while self._running:
            try:
                await self._connect_and_receive()
            except asyncio.CancelledError:
                logger.info("MeshflowWSClient: stopped")
                break
            except Exception as e:
                logger.warning(
                    f"MeshflowWSClient: connection lost ({type(e).__name__}: {e}). "
                    f"Reconnecting in {self._backoff:.0f}s..."
                )
                if self.on_disconnect:
                    try:
                        self.on_disconnect()
                    except Exception:
                        pass

            if not self._running:
                break

            # Grow exponentially to a cap; a successful connect resets
            # self._backoff to the initial value (see _connect_and_receive).
            delay = self._backoff
            self._backoff = min(delay * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
            await asyncio.sleep(delay)

        logger.info("MeshflowWSClient: run loop ended")

    def _reset_backoff_if_stable(self, connected_at: float) -> None:
        if time.monotonic() - connected_at >= STABLE_CONNECTION_SECONDS:
            self._backoff = INITIAL_BACKOFF_SECONDS

    async def _connect_and_receive(self):
        """Connect to WebSocket and receive messages until disconnect."""
        try:
            import websockets
            from websockets.exceptions import ConnectionClosed
        except ImportError:
            raise ImportError(
                "websockets package required. Install with: pip install websockets"
            )

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
            self._ws = ws
            connected_at = time.monotonic()
            got_message = False
            prefix = (
                self._feeder_pubkey_prefix_provider()
                if self._feeder_pubkey_prefix_provider
                else None
            )
            node_id = (
                self._feeder_node_id_provider()
                if self._feeder_node_id_provider
                else None
            )
            logger.info(
                "MeshflowWSClient: connected (feeder_pubkey_prefix=%s, feeder_node_id=%s)",
                prefix or "none",
                node_id if node_id is not None else "none",
            )
            if self.on_connect:
                try:
                    self.on_connect()
                except Exception as e:
                    logger.warning(f"MeshflowWSClient: on_connect error: {e}")

            while self._running:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                except asyncio.TimeoutError:
                    self._reset_backoff_if_stable(connected_at)
                    continue
                except ConnectionClosed as e:
                    self._reset_backoff_if_stable(connected_at)
                    code = getattr(getattr(e, "rcvd", None), "code", None)
                    logger.info(
                        f"MeshflowWSClient: connection closed by server (code={code})"
                    )
                    raise

                if not got_message:
                    # Data flowed, so the server really accepted us: reset the
                    # reconnect back-off (merely opening the socket isn't enough).
                    got_message = True
                    self._backoff = INITIAL_BACKOFF_SECONDS

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
                            logger.info(
                                f"MeshflowWSClient: received traceroute command, target={target_id}"
                            )
                            # Run in thread so a blocking/long-running TR doesn't block receiving
                            # further commands (e.g. multiple TRs in quick succession, or TR that never returns)
                            task = asyncio.create_task(
                                asyncio.to_thread(self.on_traceroute, target_id)
                            )

                            def _task_done(t):
                                if t.cancelled():
                                    return
                                exc = t.exception()
                                if exc:
                                    logger.warning(
                                        f"MeshflowWSClient: traceroute task failed: {exc}"
                                    )

                            task.add_done_callback(_task_done)
                        except (TypeError, ValueError):
                            logger.warning(
                                f"MeshflowWSClient: invalid traceroute target: {target}"
                            )
                    else:
                        logger.warning(
                            "MeshflowWSClient: traceroute command missing target"
                        )
                elif cmd_type == "apply_mc_channel_config":
                    channels = data.get("channels")
                    if channels is not None and self.on_apply_mc_channel_config:
                        logger.info(
                            "MeshflowWSClient: received apply_mc_channel_config (%s channels)",
                            len(channels),
                        )
                        task = asyncio.create_task(
                            asyncio.to_thread(self.on_apply_mc_channel_config, channels)
                        )

                        def _apply_done(t):
                            if t.cancelled():
                                return
                            exc = t.exception()
                            if exc:
                                logger.warning(
                                    "MeshflowWSClient: apply_mc_channel_config failed: %s",
                                    exc,
                                )

                        task.add_done_callback(_apply_done)
                    else:
                        logger.warning(
                            "MeshflowWSClient: apply_mc_channel_config missing channels or handler"
                        )
                elif cmd_type == "refresh_feeder_config":
                    if self.on_refresh_feeder_config:
                        logger.info("MeshflowWSClient: received refresh_feeder_config")
                        task = asyncio.create_task(
                            asyncio.to_thread(self.on_refresh_feeder_config)
                        )

                        def _refresh_done(t):
                            if t.cancelled():
                                return
                            exc = t.exception()
                            if exc:
                                logger.warning(
                                    "MeshflowWSClient: refresh_feeder_config failed: %s",
                                    exc,
                                )

                        task.add_done_callback(_refresh_done)
                    else:
                        logger.warning(
                            "MeshflowWSClient: refresh_feeder_config missing handler"
                        )
                else:
                    logger.debug(f"MeshflowWSClient: ignored command type: {cmd_type}")
