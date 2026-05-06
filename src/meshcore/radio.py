"""MeshCore :class:`~src.radio.interface.RadioInterface` using ``meshcore`` (asyncio)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from meshcore import MeshCore
from meshcore.events import Event, EventType

from src.meshcore.dump import dump_meshcore_event
from src.meshcore.translation import (
    event_to_incoming_packet,
    event_to_node_update,
    event_to_text_message,
)
from src.radio.errors import RadioError, call_safely, get_global_error_counter
from src.radio.events import ConnectionEstablished
from src.radio.interface import RadioHandlers, RadioInterface

logger = logging.getLogger(__name__)

# Do not JSON-dump high-frequency command plumbing (still forwarded to handlers).
_SKIP_MESHCORE_DUMP_TYPES = frozenset(
    {
        EventType.NO_MORE_MSGS,
        EventType.OK,
    }
)


class MeshCoreRadio(RadioInterface):
    """Runs ``meshcore`` on a dedicated asyncio loop in a background thread."""

    def __init__(
        self,
        *,
        serial_device: Optional[str] = None,
        ble_address: Optional[str] = None,
        ble_pin: Optional[str] = None,
        baudrate: int = 115200,
        debug: bool = False,
        data_dir: Optional[Path] = None,
    ) -> None:
        if bool(serial_device) == bool(ble_address):
            raise ValueError("Set exactly one of serial_device or ble_address")
        self._serial = serial_device
        self._ble = ble_address
        self._ble_pin = ble_pin
        self._baudrate = baudrate
        self._debug = debug
        self._data_dir = data_dir or Path("data")

        self._handlers = RadioHandlers()
        self._meshcore: Optional[MeshCore] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()
        self._started = threading.Event()
        self._startup_error: Optional[BaseException] = None
        self._connected_once = False
        self._local_node_id: Optional[str] = None
        self._error_counter = get_global_error_counter()

        self._dump_enabled = os.getenv("MESHCORE_DUMP_ENABLED", "true").lower() in (
            "1",
            "true",
            "yes",
        )

    def set_handlers(self, handlers: RadioHandlers) -> None:
        self._handlers = handlers

    def connect(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._started.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._thread_main, name="meshcore-radio", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=60.0):
            raise RadioError("MeshCoreRadio: timed out waiting for background connect")
        if self._startup_error is not None:
            raise RadioError(f"MeshCoreRadio: connect failed: {self._startup_error!r}") from self._startup_error

    def disconnect(self) -> None:
        self._shutdown.set()
        loop = self._loop
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._async_shutdown(), loop)
            try:
                fut.result(timeout=30.0)
            except Exception as exc:
                logger.warning("MeshCoreRadio disconnect: %s", exc)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._meshcore = None
        self._connected_once = False

    @property
    def is_connected(self) -> bool:
        return bool(self._meshcore and self._meshcore.is_connected)

    @property
    def local_node_id(self) -> Optional[str]:
        return self._local_node_id

    @property
    def local_nodenum(self) -> Optional[int]:
        """MeshCore nodes are pubkey-keyed; no Meshtastic-style nodenum."""
        return None

    def send_text(
        self,
        text: str,
        *,
        destination_id: Optional[str] = None,
        channel: int = 0,
        want_ack: bool = False,
        hop_limit: Optional[int] = None,
    ) -> None:
        raise RadioError("MeshCore send not implemented in 0.3 capture-only mode")

    def send_reaction(
        self,
        emoji: str,
        message_id: int,
        *,
        destination_id: Optional[str] = None,
        channel: int = 0,
    ) -> None:
        raise RadioError("MeshCore send not implemented in 0.3 capture-only mode")

    def send_traceroute(
        self,
        target_node_id: int,
        *,
        channel_index: int = 0,
    ) -> None:
        raise RadioError("MeshCore send not implemented in 0.3 capture-only mode")

    # --- internals --------------------------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._async_main())
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                logger.exception("MeshCoreRadio: error cancelling pending tasks")
            loop.close()
            self._loop = None

    async def _async_main(self) -> None:
        try:
            await self._run_session()
        except BaseException as exc:
            logger.exception("MeshCoreRadio session ended with error")
            self._startup_error = exc
            self._started.set()

    async def _run_session(self) -> None:
        max_attempts = int(os.getenv("MESHCORE_MAX_RECONNECT_ATTEMPTS", "100"))
        if self._serial:
            mc = await MeshCore.create_serial(
                self._serial,
                self._baudrate,
                debug=self._debug,
                auto_reconnect=True,
                max_reconnect_attempts=max_attempts,
            )
        else:
            mc = await MeshCore.create_ble(
                self._ble,
                pin=self._ble_pin,
                debug=self._debug,
                auto_reconnect=True,
                max_reconnect_attempts=max_attempts,
            )
        if mc is None:
            raise RadioError("MeshCore.create_* returned None (device not responding)")

        self._meshcore = mc

        mc.subscribe(None, self._on_any_event)

        await mc.start_auto_message_fetching()

        self_info_evt = await mc.wait_for_event(EventType.SELF_INFO, timeout=5.0)
        pubkey = ""
        if self_info_evt and isinstance(self_info_evt.payload, dict):
            pubkey = str(self_info_evt.payload.get("public_key", "") or "")
        if not pubkey and mc.self_info:
            pubkey = str(mc.self_info.get("public_key", "") or "")
        self._local_node_id = f"mc:{pubkey[:12]}" if pubkey else "mc:unknown"

        if not self._connected_once:
            self._connected_once = True
            if self._handlers.on_connection_established:
                call_safely(
                    "meshcore.on_connection_established",
                    self._handlers.on_connection_established,
                    ConnectionEstablished(
                        local_node_id=self._local_node_id,
                        local_nodenum=0,
                        extras={"meshcore": True, "public_key_prefix": pubkey[:12]},
                    ),
                    counter=self._error_counter,
                )

        self._started.set()
        await self._wait_until_shutdown()

    async def _wait_until_shutdown(self) -> None:
        while not self._shutdown.is_set():
            await asyncio.sleep(0.25)

    async def _async_shutdown(self) -> None:
        mc = self._meshcore
        if mc:
            try:
                await mc.disconnect()
            except Exception:
                logger.exception("MeshCore.disconnect failed")
        self._meshcore = None

    async def _on_any_event(self, event: Event) -> None:
        """Central ingress: dump, then translate to bot handlers."""
        try:
            self._dispatch_meshcore_event(event)
        except Exception:
            self._error_counter.increment("meshcore.on_any_event")
            logger.exception("MeshCoreRadio._on_any_event")

    def dispatch_meshcore_event_for_tests(self, event: Event) -> None:
        """Synchronous hook for unit tests (same path as async subscriber)."""
        self._dispatch_meshcore_event(event)

    def _dispatch_meshcore_event(self, event: Event) -> None:
        et = event.type
        if self._dump_enabled and et not in _SKIP_MESHCORE_DUMP_TYPES:
            dump_meshcore_event(
                event_type=et.value,
                payload=event.payload,
                attributes=dict(event.attributes) if event.attributes else {},
                base_dir=self._data_dir,
            )

        if et == EventType.DISCONNECTED:
            reason = ""
            if isinstance(event.payload, dict):
                reason = str(event.payload.get("reason", ""))
            if self._handlers.on_disconnected:
                err: Optional[Exception] = RadioError(reason) if reason else None
                call_safely(
                    "meshcore.on_disconnected",
                    self._handlers.on_disconnected,
                    err,
                    counter=self._error_counter,
                )
            return

        incoming = event_to_incoming_packet(event)
        if incoming and self._handlers.on_packet:
            call_safely(
                "meshcore.on_packet",
                self._handlers.on_packet,
                incoming,
                counter=self._error_counter,
            )

        text = event_to_text_message(event, local_node_id=self._local_node_id)
        if text and text.text and self._handlers.on_text_message:
            call_safely(
                "meshcore.on_text_message",
                self._handlers.on_text_message,
                text,
                counter=self._error_counter,
            )

        node_upd = event_to_node_update(event)
        if node_upd and self._handlers.on_node_update:
            call_safely(
                "meshcore.on_node_update",
                self._handlers.on_node_update,
                node_upd,
                counter=self._error_counter,
            )
