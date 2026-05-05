"""HTTP client for the meshflow-api ingest endpoints.

Protocol-agnostic: takes a :class:`PacketSerializer` to shape outgoing data,
and a ``local_nodenum_provider`` callable so it can lazily look up the local
nodenum for v2 endpoints (which are scoped per-node).
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from requests import HTTPError, RequestException

from src.api.BaseAPIWrapper import BaseAPIWrapper
from src.api.packet_serializer import PacketSerializer
from src.data_classes import MeshNode
from src.radio.errors import get_global_error_counter

logger = logging.getLogger(__name__)


class StorageAPIWrapper(BaseAPIWrapper):
    """Uploads packets and node data to a meshflow-api instance."""

    failed_packets_dir: Optional[Path]

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        api_version: int = 1,
        failed_packets_dir: Optional[Union[str, Path]] = None,
        *,
        serializer: PacketSerializer,
        local_nodenum_provider: Callable[[], Optional[int]],
    ):
        super().__init__(base_url, token)
        self.api_version = api_version
        self.failed_packets_dir = (
            Path(failed_packets_dir) if failed_packets_dir else None
        )
        self._serializer = serializer
        self._local_nodenum_provider = local_nodenum_provider
        self._error_counter = get_global_error_counter()

    def _get_url(self, path: str, args: Optional[dict] = None) -> str:
        if args is None:
            args = {}

        if self.api_version == 1:
            api_paths = {
                "raw_packet": "/api/raw-packet/",
                "nodes": "/api/nodes/",
                "node_by_id": f"/api/nodes/{args.get('node_id', '')}",
            }
        else:
            local_nodenum = self._local_nodenum_provider()
            api_paths = {
                "raw_packet": f"/api/packets/{local_nodenum}/ingest/",
                "nodes": f"/api/packets/{local_nodenum}/nodes/",
                "node_by_id": f"/api/nodes/{args.get('node_id', '')}",
            }
        return api_paths[path]

    # --- raw packets ------------------------------------------------------

    def store_raw_packet(self, packet: Any) -> Optional[dict]:
        """Sanitise and upload a received packet. Returns the api response or
        ``None`` if upload failed; never raises (errors are dumped to disk
        when ``failed_packets_dir`` is configured)."""
        try:
            payload = self._serializer.serialise_raw_packet(packet)
        except Exception as exc:
            self._error_counter.increment("storage.serialise_raw_packet")
            logger.exception("StorageAPIWrapper: serialise_raw_packet failed: %s", exc)
            return None

        logger.debug("Storing packet: %s", payload)
        try:
            response = self._post(self._get_url("raw_packet"), json=payload)
            return response.json()
        except HTTPError as exc:
            self._error_counter.increment("storage.store_raw_packet.http")
            logger.error("HTTP error storing packet: %s", exc.response.text)
            if self.failed_packets_dir:
                self._dump_failed_packet(payload, exc, original_packet=packet)
        except RequestException as exc:
            self._error_counter.increment("storage.store_raw_packet.network")
            logger.error("Network error storing packet: %s", exc)
            if self.failed_packets_dir:
                self._dump_failed_packet(payload, exc, original_packet=packet)
        except Exception as exc:
            self._error_counter.increment("storage.store_raw_packet.unexpected")
            logger.exception("Unexpected error storing packet: %s", exc)
            if self.failed_packets_dir:
                self._dump_failed_packet(payload, exc, original_packet=packet)
        return None

    # --- nodes ------------------------------------------------------------

    def list_nodes(self) -> list[MeshNode]:
        response = self._get(self._get_url("nodes"))
        return [self._serializer.deserialise_node(node) for node in response.json()]

    def store_node(self, node: MeshNode) -> Optional[dict]:
        try:
            payload = self._serializer.serialise_node(node)
            response = self._post(self._get_url("nodes"), json=payload)
            return response.json()
        except HTTPError as exc:
            self._error_counter.increment("storage.store_node.http")
            logger.error("HTTP error storing node: %s", exc.response.text)
        except RequestException as exc:
            self._error_counter.increment("storage.store_node.network")
            logger.error("Network error storing node: %s", exc)
        except Exception as exc:
            self._error_counter.increment("storage.store_node.unexpected")
            logger.exception("Unexpected error storing node: %s", exc)
        return None

    def get_node_by_id(
        self,
        node_id: Union[int, str],
        include_positions: int = 0,
        include_metrics: int = 0,
    ) -> Optional[MeshNode]:
        response = self._get(
            f"{self._get_url('node_by_id', args={'node_id': node_id})}"
            f"?positions={include_positions}&metrics={include_metrics}"
        )
        node_data = response.json()
        return self._serializer.deserialise_node(node_data) if node_data else None

    # --- failed-packet dump ----------------------------------------------

    def _dump_failed_packet(
        self,
        payload: dict,
        exc: Exception,
        *,
        original_packet: Any = None,
    ) -> None:
        if self.failed_packets_dir is None:
            return

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        os.makedirs(self.failed_packets_dir, exist_ok=True)

        # Error metadata
        try:
            error_info = {
                "exception_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
            response = getattr(exc, "response", None)
            if response is not None:
                error_info.update(
                    status_code=response.status_code,
                    reason=response.reason,
                    text=response.text,
                    url=response.url,
                    headers=dict(response.headers),
                )
            with (self.failed_packets_dir / f"failed_packet_{timestamp}_error.json").open("w") as f:
                json.dump(error_info, f, indent=4)
        except Exception as dump_exc:
            logger.error("Failed to dump error info: %s", dump_exc)

        # Sanitised payload (always JSON-safe)
        try:
            with (self.failed_packets_dir / f"failed_packet_{timestamp}.json").open("w") as f:
                json.dump(payload, f, indent=4)
        except Exception as dump_exc:
            logger.error("Failed to dump packet payload: %s", dump_exc)

        # Underlying protobuf (best-effort)
        raw_proto = (
            original_packet.get("raw")
            if isinstance(original_packet, dict)
            else None
        )
        if raw_proto:
            try:
                with (self.failed_packets_dir / f"failed_packet_{timestamp}_raw.txt").open("w") as f:
                    f.write(str(raw_proto))
            except Exception as dump_exc:
                logger.error("Failed to dump raw protobuf: %s", dump_exc)
