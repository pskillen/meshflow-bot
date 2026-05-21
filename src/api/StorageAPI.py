"""HTTP client for the meshflow-api ingest endpoints.

Meshtastic uploads use v2 paths scoped by local nodenum:
``POST /api/packets/{nodenum}/ingest/`` and ``…/nodes/`` (see ``_get_url`` when
``api_version == 2``). v1 ``POST /api/raw-packet/`` is legacy.

MeshCore uploads use feeder-scoped paths:
``POST /api/meshcore/feeders/{prefix}/packets/ingest/`` (and channel sync / bot-version).

Takes a :class:`PacketSerializer` to shape outgoing data, optional Meshtastic nodenum
provider, and optional MeshCore feeder identity providers.
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
from src.meshcore.serializers import MeshCoreSkipUpload
from src.radio.errors import get_global_error_counter
from src.version import get_bot_version

logger = logging.getLogger(__name__)

MESHCORE_FEEDER_PUBKEY_HEADER = "X-MeshCore-Feeder-Pubkey"


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
        local_meshtastic_nodenum_provider: Callable[[], Optional[int]],
        meshcore_feeder_prefix_provider: Optional[Callable[[], Optional[str]]] = None,
        meshcore_feeder_pubkey_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        super().__init__(base_url, token)
        self.api_version = api_version
        self.failed_packets_dir = (
            Path(failed_packets_dir) if failed_packets_dir else None
        )
        self._serializer = serializer
        self._local_meshtastic_nodenum_provider = local_meshtastic_nodenum_provider
        self._meshcore_feeder_prefix_provider = meshcore_feeder_prefix_provider
        self._meshcore_feeder_pubkey_provider = meshcore_feeder_pubkey_provider
        self._error_counter = get_global_error_counter()

    def _get_headers(self) -> dict:
        headers = super()._get_headers()
        if self._meshcore_feeder_pubkey_provider:
            pubkey = self._meshcore_feeder_pubkey_provider()
            if pubkey:
                headers[MESHCORE_FEEDER_PUBKEY_HEADER] = pubkey
        return headers

    def _meshcore_feeder_prefix(self) -> Optional[str]:
        if not self._meshcore_feeder_prefix_provider:
            return None
        return self._meshcore_feeder_prefix_provider()

    def _meshcore_feeder_url(self, suffix: str) -> str:
        prefix = self._meshcore_feeder_prefix()
        if not prefix:
            raise ValueError("MeshCore feeder pubkey prefix not available yet")
        return f"/api/meshcore/feeders/{prefix}/{suffix}"

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
            local_nodenum = self._local_meshtastic_nodenum_provider()
            api_paths = {
                "raw_packet": f"/api/packets/{local_nodenum}/ingest/",
                "nodes": f"/api/packets/{local_nodenum}/nodes/",
                "bot_version": f"/api/packets/{local_nodenum}/bot-version/",
                "node_by_id": f"/api/nodes/{args.get('node_id', '')}",
            }
        return api_paths[path]

    def report_bot_version(self) -> bool:
        """Report meshflow-bot version to the API (v2 only). Returns True on success."""
        if self.api_version != 2:
            logger.debug(
                "Skipping bot version report (api_version=%s)", self.api_version
            )
            return False

        version = get_bot_version()
        prefix = self._meshcore_feeder_prefix()
        if prefix:
            url = self._meshcore_feeder_url("bot-version/")
        else:
            local_nodenum = self._local_meshtastic_nodenum_provider()
            if local_nodenum is None:
                logger.warning(
                    "Cannot report bot version: nodenum and MeshCore prefix unavailable"
                )
                return False
            url = self._get_url("bot_version")

        try:
            self._put(url, json={"bot_version": version})
            logger.info("Reported bot version %s to API", version)
            return True
        except HTTPError as exc:
            self._error_counter.increment("storage.report_bot_version.http")
            logger.error("HTTP error reporting bot version: %s", exc.response.text)
        except RequestException as exc:
            self._error_counter.increment("storage.report_bot_version.network")
            logger.error("Network error reporting bot version: %s", exc)
        except Exception as exc:
            self._error_counter.increment("storage.report_bot_version.unexpected")
            logger.exception("Unexpected error reporting bot version: %s", exc)
        return False

    # --- raw packets ------------------------------------------------------

    def store_raw_meshcore_packet(self, packet: Any) -> Optional[dict]:
        """Upload a MeshCore capture envelope to the feeder-scoped ingest path."""
        try:
            payload = self._serializer.serialise_raw_packet(packet)
        except MeshCoreSkipUpload as exc:
            logger.debug("Skipping MeshCore upload: %s", exc)
            return None
        except Exception as exc:
            self._error_counter.increment("storage.serialise_raw_meshcore_packet")
            logger.exception(
                "StorageAPIWrapper: serialise_raw_meshcore_packet failed: %s", exc
            )
            return None

        try:
            url = self._meshcore_feeder_url("packets/ingest/")
        except ValueError:
            logger.warning(
                "Cannot store MeshCore packet: feeder pubkey prefix not available yet"
            )
            return None

        logger.debug("Storing MeshCore packet: %s", payload.get("payload_type"))
        try:
            response = self._post(url, json=payload)
            return response.json()
        except HTTPError as exc:
            self._error_counter.increment("storage.store_raw_meshcore_packet.http")
            logger.error("HTTP error storing MeshCore packet: %s", exc.response.text)
            if self.failed_packets_dir:
                self._dump_failed_packet(payload, exc, original_packet=packet)
        except RequestException as exc:
            self._error_counter.increment("storage.store_raw_meshcore_packet.network")
            logger.error("Network error storing MeshCore packet: %s", exc)
            if self.failed_packets_dir:
                self._dump_failed_packet(payload, exc, original_packet=packet)
        except Exception as exc:
            self._error_counter.increment(
                "storage.store_raw_meshcore_packet.unexpected"
            )
            logger.exception("Unexpected error storing MeshCore packet: %s", exc)
            if self.failed_packets_dir:
                self._dump_failed_packet(payload, exc, original_packet=packet)
        return None

    def post_mc_channel_sync(self, body: dict) -> bool:
        """POST device channel snapshot to the feeder-scoped mc-channel-sync path."""
        try:
            url = self._meshcore_feeder_url("mc-channel-sync/")
        except ValueError:
            logger.warning(
                "Cannot post MC channel sync: feeder pubkey prefix not available yet"
            )
            return False
        try:
            response = self._post(url, json=body)
            return response.status_code in (200, 201)
        except HTTPError as exc:
            self._error_counter.increment("storage.post_mc_channel_sync.http")
            logger.error(
                "HTTP error posting MC channel sync to %s: %s",
                self.base_url,
                exc.response.text,
            )
        except RequestException as exc:
            self._error_counter.increment("storage.post_mc_channel_sync.network")
            logger.error("Network error posting MC channel sync: %s", exc)
        except Exception as exc:
            self._error_counter.increment("storage.post_mc_channel_sync.unexpected")
            logger.exception("Unexpected error posting MC channel sync: %s", exc)
        return False

    def store_raw_packet(self, packet: Any) -> Optional[dict]:
        """Sanitise and upload a Meshtastic packet to v2 ``/api/packets/{nodenum}/ingest/``
        (or v1 ``/api/raw-packet/``). Returns the api response or ``None`` if upload failed;
        never raises (errors are dumped to disk when ``failed_packets_dir`` is configured).
        For MeshCore captures use :meth:`store_raw_meshcore_packet` instead."""
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
            with (
                self.failed_packets_dir / f"failed_packet_{timestamp}_error.json"
            ).open("w") as f:
                json.dump(error_info, f, indent=4)
        except Exception as dump_exc:
            logger.error("Failed to dump error info: %s", dump_exc)

        # Sanitised payload (always JSON-safe)
        try:
            with (self.failed_packets_dir / f"failed_packet_{timestamp}.json").open(
                "w"
            ) as f:
                json.dump(payload, f, indent=4)
        except Exception as dump_exc:
            logger.error("Failed to dump packet payload: %s", dump_exc)

        # Underlying protobuf (best-effort)
        raw_proto = (
            original_packet.get("raw") if isinstance(original_packet, dict) else None
        )
        if raw_proto:
            try:
                with (
                    self.failed_packets_dir / f"failed_packet_{timestamp}_raw.txt"
                ).open("w") as f:
                    f.write(str(raw_proto))
            except Exception as dump_exc:
                logger.error("Failed to dump raw protobuf: %s", dump_exc)
