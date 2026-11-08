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
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, RequestException, Timeout
from requests.exceptions import InvalidURL, SSLError

from src.api.BaseAPIWrapper import BaseAPIWrapper
from src.api.packet_serializer import PacketSerializer
from src.api.retry_worker import DEFAULT_GAP_SECONDS, RetryWorker
from src.data_classes import MeshNode
from src.meshtastic.identity import FeederIdentity
from src.meshcore.serializers import MeshCoreSkipUpload
from src.radio.errors import get_global_error_counter
from src.version import get_bot_version

logger = logging.getLogger(__name__)

MESHCORE_FEEDER_PUBKEY_HEADER = "X-MeshCore-Feeder-Pubkey"

# Meshtastic calls answer 403/409 when the API cannot accept this feeder as it
# identifies itself (e.g. the 2.8 node-number change). Don't hammer it.
IDENTITY_REJECTION_STATUSES = (403, 409)
IDENTITY_BACKOFF_INITIAL_SECONDS = 30.0
IDENTITY_BACKOFF_MAX_SECONDS = 900.0

# Feeder-scoped (v4) URLs: ``auto`` probes the API, ``on`` assumes v4 (and still
# falls back on a 404), ``off`` never uses v4.
FEEDER_URLS_MODES = ("auto", "on", "off")
FEEDER_IDENTITY_PATH = "/api/v4/feeder/identity/"
V4_PREFIX = "/api/v4/feeder"


def parse_feeder_urls_mode(value: Optional[str], name: str = "") -> str:
    """Normalise a ``STORAGE_API_*_FEEDER_URLS`` setting; unknown means ``auto``."""
    mode = (value or "auto").strip().lower()
    if mode not in FEEDER_URLS_MODES:
        logger.warning(
            "Ignoring invalid %s=%r (use auto, on or off); using auto", name, value
        )
        return "auto"
    return mode


# Connect-time calls (bot version report, per-node NodeDB sync) are retried in
# the background on a transient failure (no connection, timeout, HTTP 5xx):
# three attempts in all, at 0s, +15s and +60s. One worker thread sends the
# retries serially (see ``RetryWorker``).
RETRY_DELAYS_SECONDS = (15.0, 45.0)


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
        meshtastic_identity_provider: Optional[Callable[[], FeederIdentity]] = None,
        clock: Callable[[], float] = time.monotonic,
        retry_delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
        retry_gap: float = DEFAULT_GAP_SECONDS,
        feeder_urls_mode: str = "auto",
        on_feeder_urls_change: Optional[Callable[[bool], None]] = None,
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
        self._meshtastic_identity_provider = meshtastic_identity_provider
        self._clock = clock
        self._identity_backoff_seconds = 0.0
        self._identity_blocked_until = 0.0
        self._error_counter = get_global_error_counter()
        self._retry_delays = retry_delays
        self._retry_worker = RetryWorker(gap=retry_gap, clock=clock)
        self.feeder_urls_mode = parse_feeder_urls_mode(feeder_urls_mode)
        self._on_feeder_urls_change = on_feeder_urls_change
        # True once this destination is known to serve the v4 feeder URLs.
        # Meshtastic only: MeshCore keeps its prefix URLs, and api_version 1
        # (the oldest URLs) never uses v4.
        self.uses_v4 = self._v4_eligible() and self.feeder_urls_mode == "on"

    def _v4_eligible(self) -> bool:
        return self._meshcore_feeder_prefix_provider is None and self.api_version != 1

    def _set_uses_v4(self, value: bool) -> None:
        if value == self.uses_v4:
            return
        self.uses_v4 = value
        logger.info(
            "API %s: using %s feeder URLs",
            self.base_url,
            "v4 (feeder-scoped)" if value else "legacy",
        )
        if self._on_feeder_urls_change:
            try:
                self._on_feeder_urls_change(value)
            except Exception as exc:
                logger.warning("Feeder URL change callback failed: %s", exc)

    # --- v4 feeder URL probe ---------------------------------------------

    def probe_feeder_urls(self) -> None:
        """Ask ``GET /api/v4/feeder/identity/`` whether this API has the v4
        feeder URLs: 200 switches to v4, 404 to legacy, 403 ``shared_api_key``
        stays legacy (ERROR). Any other answer or a network error leaves the
        mode unchanged. A probe is not an upload, so it never starts the
        identity back-off."""
        if not self._v4_eligible() or self.feeder_urls_mode == "off":
            return
        try:
            self._get(FEEDER_IDENTITY_PATH)
        except HTTPError as exc:
            self._handle_probe_rejection(exc)
            return
        except RequestException as exc:
            logger.warning(
                "API %s: feeder URL probe failed (%s); keeping current URLs",
                self.base_url,
                exc,
            )
            return
        except Exception as exc:
            logger.warning("Unexpected error probing %s: %s", self.base_url, exc)
            return
        self._set_uses_v4(True)

    def _handle_probe_rejection(self, exc: HTTPError) -> None:
        status = getattr(exc.response, "status_code", None)
        if status == 404:
            self._set_uses_v4(False)
            return
        code = None
        if status == 403:
            try:
                code = exc.response.json().get("code")
            except Exception:
                code = None
        if code == "shared_api_key":
            self._set_uses_v4(False)
            logger.error(
                "API %s: this API key is shared by more than one feeder, so the "
                "feeder-scoped (v4) URLs are refused; using legacy URLs. Ask the "
                "Meshflow owner to mint one API key per feeder "
                "(see docs/MESHTASTIC.md, 'Feeder-scoped URLs').",
                self.base_url,
            )
            return
        logger.warning(
            "API %s: feeder URL probe answered HTTP %s%s; keeping current URLs",
            self.base_url,
            status,
            f" ({code})" if code else "",
        )

    def _v4_gone(self, exc: HTTPError) -> bool:
        """A 404 from a v4 call means the API no longer has v4 (rollback):
        drop to legacy and probe again at once. Returns True if that happened."""
        if not self.uses_v4 or getattr(exc.response, "status_code", None) != 404:
            return False
        logger.warning("API %s: v4 feeder URL returned 404; re-probing", self.base_url)
        self._set_uses_v4(False)
        self.probe_feeder_urls()
        return True

    def shutdown(self) -> None:
        """Stop the retry thread (non-blocking); pending retries are dropped."""
        self._retry_worker.stop()

    # --- transient-failure retry ------------------------------------------

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        """No connection, timeouts and HTTP 5xx are worth retrying. 4xx
        (including the 403/409 identity rejections, which have their own
        back-off), TLS failures and malformed URLs will not fix themselves."""
        if isinstance(exc, HTTPError):
            status = getattr(exc.response, "status_code", None)
            return status is not None and status >= 500
        if isinstance(exc, (SSLError, InvalidURL)):
            return False
        return isinstance(exc, (RequestsConnectionError, Timeout))

    def _schedule_retry(
        self,
        key: str,
        gen: int,
        fn: Callable[[Any, int], Any],
        payload: Any,
        retries_done: int,
    ) -> None:
        """Run ``fn(payload, retries_done + 1)`` later on the retry worker
        (never on the caller's thread)."""
        if retries_done >= len(self._retry_delays):
            logger.error("Giving up on %s after %s attempts", key, retries_done + 1)
            return
        delay = self._retry_delays[retries_done]
        if self._retry_worker.schedule(key, gen, delay, fn, payload, retries_done + 1):
            logger.info("Will retry %s in %.0fs", key, delay)

    def _log_failure(self, retries_done: int, msg: str, *args: Any) -> None:
        """The first failure is an ERROR; a failed retry is only a WARNING
        (the give-up line carries the summary)."""
        logger.log(logging.WARNING if retries_done else logging.ERROR, msg, *args)

    def _meshtastic_identity(self) -> Optional[FeederIdentity]:
        if not self._meshtastic_identity_provider:
            return None
        try:
            return self._meshtastic_identity_provider()
        except Exception as exc:
            logger.debug("Could not read feeder identity: %s", exc)
            return None

    # --- identity rejection backoff ---------------------------------------

    def _identity_backoff_active(self) -> bool:
        return self._clock() < self._identity_blocked_until

    def _note_identity_ok(self) -> None:
        self._identity_backoff_seconds = 0.0
        self._identity_blocked_until = 0.0

    def _handle_identity_rejection(self, exc: HTTPError, what: str) -> bool:
        """On 403/409 from a Meshtastic call: log an actionable ERROR naming
        the reported node number and start/extend a backoff. Returns ``True``
        if ``exc`` was such a rejection."""
        status = getattr(exc.response, "status_code", None)
        if (
            status not in IDENTITY_REJECTION_STATUSES
            or not self._meshtastic_identity_provider
        ):
            return False
        identity = self._meshtastic_identity()
        reported = identity.node_num if identity else None
        self._identity_backoff_seconds = min(
            max(self._identity_backoff_seconds * 2, IDENTITY_BACKOFF_INITIAL_SECONDS),
            IDENTITY_BACKOFF_MAX_SECONDS,
        )
        self._identity_blocked_until = self._clock() + self._identity_backoff_seconds
        self._error_counter.increment("storage.identity_rejected")
        logger.error(
            "API %s refused %s with HTTP %s while reporting node number %s. "
            "Meshtastic 2.8 derives the node number from the radio's public key, "
            "so a firmware upgrade can change it and the API may not recognise "
            "this feeder under the new number; check the feeder's API key and "
            "linked node in Meshflow (see docs/MESHTASTIC.md, 'Feeder identity'). "
            "Pausing uploads for %.0fs. Response: %s",
            self.base_url,
            what,
            status,
            reported,
            self._identity_backoff_seconds,
            getattr(exc.response, "text", ""),
        )
        return True

    def _get_headers(self) -> dict:
        headers = super()._get_headers()
        identity = self._meshtastic_identity()
        if identity:
            headers.update(identity.headers())
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

        if self.uses_v4:
            return {
                "raw_packet": f"{V4_PREFIX}/meshtastic/ingest/",
                "nodes": f"{V4_PREFIX}/meshtastic/nodes/",
                "bot_version": f"{V4_PREFIX}/bot-version/",
                "node_by_id": f"/api/nodes/{args.get('node_id', '')}",
            }[path]

        if self.api_version == 1:
            api_paths = {
                "raw_packet": "/api/raw-packet/",
                "nodes": "/api/nodes/",
                "node_by_id": f"/api/nodes/{args.get('node_id', '')}",
            }
        else:
            local_nodenum = self._local_meshtastic_nodenum_provider()
            if self.api_version == 3:
                prefix = f"/api/v3/packets/{local_nodenum}"
            else:
                prefix = f"/api/packets/{local_nodenum}"
            api_paths = {
                "raw_packet": f"{prefix}/ingest/",
                "nodes": f"{prefix}/nodes/",
                "bot_version": f"{prefix}/bot-version/",
                "node_by_id": f"/api/nodes/{args.get('node_id', '')}",
            }
        return api_paths[path]

    def report_bot_version(self) -> bool:
        """Report meshflow-bot version to the API (v2/v3). Returns True on
        success; a transient failure is retried in the background. A newer
        call drops the pending retry."""
        gen = self._retry_worker.begin("bot_version")
        return self._report_bot_version_attempt(gen, 0)

    def _retry_report_bot_version(self, gen: int, retries_done: int) -> None:
        if self._identity_backoff_active():
            self._error_counter.increment("storage.report_bot_version.backoff")
            logger.info("Dropping bot version retry: backing off after rejection")
            return
        self._report_bot_version_attempt(gen, retries_done)

    def _report_bot_version_attempt(self, gen: int, retries_done: int) -> bool:
        if self.api_version not in (2, 3) and not self.uses_v4:
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
            if local_nodenum is None and not self.uses_v4:
                logger.warning(
                    "Cannot report bot version: nodenum and MeshCore prefix unavailable"
                )
                return False
            url = self._get_url("bot_version")

        def retry() -> None:
            self._schedule_retry(
                "bot_version", gen, self._retry_report_bot_version, gen, retries_done
            )

        try:
            payload: dict[str, Any] = {"bot_version": version}
            identity = self._meshtastic_identity()
            if identity and not prefix:
                payload.update(identity.bot_version_fields())
            self._put(url, json=payload)
            logger.info("Reported bot version %s to API", version)
            return True
        except HTTPError as exc:
            self._error_counter.increment("storage.report_bot_version.http")
            if self._v4_gone(exc):
                pass
            elif not self._handle_identity_rejection(exc, "the bot version report"):
                self._log_failure(
                    retries_done,
                    "HTTP error reporting bot version: %s",
                    exc.response.text,
                )
                if self._is_transient(exc):
                    retry()
        except RequestException as exc:
            self._error_counter.increment("storage.report_bot_version.network")
            self._log_failure(
                retries_done, "Network error reporting bot version: %s", exc
            )
            if self._is_transient(exc):
                retry()
        except Exception as exc:
            self._error_counter.increment("storage.report_bot_version.unexpected")
            logger.exception("Unexpected error reporting bot version: %s", exc)
        return False

    def fetch_bot_config(self) -> Optional[dict]:
        """Fetch operator config for this MeshCore feeder (interval hours, etc.)."""
        prefix = self._meshcore_feeder_prefix()
        if not prefix:
            logger.debug("Skipping bot config fetch: MeshCore prefix unavailable")
            return None
        try:
            url = self._meshcore_feeder_url("bot-config/")
            response = self._get(url)
            return response.json()
        except HTTPError as exc:
            self._error_counter.increment("storage.fetch_bot_config.http")
            logger.error("HTTP error fetching bot config: %s", exc.response.text)
        except RequestException as exc:
            self._error_counter.increment("storage.fetch_bot_config.network")
            logger.error("Network error fetching bot config: %s", exc)
        except Exception as exc:
            self._error_counter.increment("storage.fetch_bot_config.unexpected")
            logger.exception("Unexpected error fetching bot config: %s", exc)
        return None

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

        if self._identity_backoff_active():
            self._error_counter.increment("storage.store_raw_packet.backoff")
            logger.debug("Skipping packet upload: backing off after identity rejection")
            return None

        logger.debug("Storing packet: %s", payload)
        try:
            response = self._post(self._get_url("raw_packet"), json=payload)
            self._note_identity_ok()
            return response.json()
        except HTTPError as exc:
            self._error_counter.increment("storage.store_raw_packet.http")
            if self._v4_gone(exc):
                pass
            elif not self._handle_identity_rejection(exc, "a packet upload"):
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
        """Upload a node; a transient failure is retried in the background
        (this is what makes the connect-time NodeDB sync resilient). A newer
        call for the same node drops that node's pending retry."""
        node_id = getattr(getattr(node, "user", None), "id", None)
        gen = self._retry_worker.begin(f"node:{node_id}")
        return self._store_node_attempt(node, gen, 0)

    def _retry_store_node(
        self, payload: tuple[MeshNode, int], retries_done: int
    ) -> None:
        node, gen = payload
        self._store_node_attempt(node, gen, retries_done)

    def _store_node_attempt(
        self, node: MeshNode, gen: int, retries_done: int
    ) -> Optional[dict]:
        node_id = getattr(getattr(node, "user", None), "id", None)

        def retry() -> None:
            self._schedule_retry(
                f"node:{node_id}",
                gen,
                self._retry_store_node,
                (node, gen),
                retries_done,
            )

        if self._identity_backoff_active():
            self._error_counter.increment("storage.store_node.backoff")
            return None
        try:
            payload = self._serializer.serialise_node(node)
            response = self._post(self._get_url("nodes"), json=payload)
            self._note_identity_ok()
        except HTTPError as exc:
            self._error_counter.increment("storage.store_node.http")
            if self._v4_gone(exc):
                pass
            elif not self._handle_identity_rejection(exc, f"node {node_id}"):
                self._log_failure(
                    retries_done,
                    "HTTP error storing node %s: %s",
                    node_id,
                    exc.response.text,
                )
                if self._is_transient(exc):
                    retry()
            return None
        except RequestException as exc:
            self._error_counter.increment("storage.store_node.network")
            self._log_failure(retries_done, "Network error storing node: %s", exc)
            if self._is_transient(exc):
                retry()
            return None
        except Exception as exc:
            self._error_counter.increment("storage.store_node.unexpected")
            logger.exception("Unexpected error storing node: %s", exc)
            return None
        try:
            # Outside the retried region: a 2xx with a bad body was accepted,
            # so re-sending it would only duplicate the upload.
            return response.json()
        except ValueError as exc:
            self._error_counter.increment("storage.store_node.bad_body")
            logger.warning(
                "Node %s accepted but the response was not JSON: %s", node_id, exc
            )
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
