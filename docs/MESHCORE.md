# MeshCore (Phase 0.3 — capture-only)

[MeshCore](https://meshcore.co.uk) is a mesh radio protocol and companion firmware family. This bot integrates via the [`meshcore` PyPI package](https://github.com/meshcore-dev/meshcore_py) (Python bindings).

**Phase 0.3 scope:** connect, receive events, translate them into the bot’s generic `RadioInterface` events, and write JSON captures under `data/meshcore_packets/<event_type>/`. **No** Meshflow API upload (`StorageAPIWrapper` is disabled when `RADIO_PROTOCOL=meshcore`).

## Transports

| Transport | Env vars | Notes |
|-----------|-----------|--------|
| **USB serial** (default) | `MESHCORE_SERIAL_DEVICE` (e.g. `/dev/ttyUSB0`) | On Linux, user usually needs `dialout` group membership for the device node. |
| **Bluetooth LE** | `MESHCORE_BLE_ADDRESS` (e.g. `AA:BB:CC:DD:EE:FF`), optional `MESHCORE_BLE_PIN` | Set **either** serial **or** BLE, not both. Requires platform BLE stack + `meshcore` dependencies. |

TCP is supported by `meshcore` but not wired in this bot build (add later if needed).

## Environment variables

| Variable | Description |
|----------|-------------|
| `RADIO_PROTOCOL` | Must be `meshcore` for this mode. |
| `MESHCORE_SERIAL_DEVICE` | Serial device path (mutually exclusive with BLE). |
| `MESHCORE_BLE_ADDRESS` | BLE MAC / address (mutually exclusive with serial). |
| `MESHCORE_BLE_PIN` | Optional pairing PIN string. |
| `MESHCORE_SERIAL_BAUD` | Serial baud rate (default `115200`). |
| `MESHCORE_DEBUG` | `true` / `1` enables verbose `meshcore` logging. |
| `MESHCORE_DUMP_ENABLED` | `true` / `false` — write JSON dumps (default `true`). |
| `MESHCORE_MAX_RECONNECT_ATTEMPTS` | Passed to `meshcore` auto-reconnect (default `100`). |
| `ADMIN_NODES` | Same as Meshtastic: comma-separated admin ids (format may evolve for MC). |
| `DATA_DIR` | Base data directory (default `data/`). |

`STORAGE_API_*` is ignored with a log line in Phase 0.3. The MeshCore WebSocket command channel is not started (traceroute is Meshtastic-only today).

## Local identity

MeshCore nodes are identified by **Ed25519 public keys** (64 hex chars), not Meshtastic-style 32-bit node numbers.

- `MeshCoreRadio.local_node_id` is exposed as `mc:` + the first **12** hex characters of the companion’s public key after `SELF_INFO` (or `mc:unknown` if that event is missing).
- `local_nodenum` is always `None` for MeshCore. `ConnectionEstablished.local_nodenum` is set to `0` as a placeholder for logging only.

Remote senders in DMs use ids like `mc:p:<12-hex-prefix>` when only a short prefix is on the wire.

## Running

```bash
source venv/bin/activate
export RADIO_PROTOCOL=meshcore
export MESHCORE_SERIAL_DEVICE=/dev/ttyUSB0
python -m src.main
```

Docker Compose: use the `meshflow-bot-meshcore` service in `docker-compose.yaml` (pass-through of `/dev/ttyUSB0` is Linux-specific; adjust the device path for your host).

## Capture layout

Each JSON file:

- Top-level `"protocol": "meshcore"`.
- `event_type`, `payload`, `attributes` mirroring `meshcore.events.Event`.

High-frequency types `no_more_messages` and `command_ok` are **not** written to disk (still processed for the live session).

## Phase 0.4 — capture campaign (complete)

Real-world JSON captures and capture-verified field tables live under **[docs/meshcore_packets/](meshcore_packets/README.md)**:

- [README.md](meshcore_packets/README.md) — duration, geography, feeder setup, sample index.
- [MESHCORE_PACKET_FIELDS.md](meshcore_packets/MESHCORE_PACKET_FIELDS.md) — field-by-field tables from those files.

Tracked in [meshflow-api#275](https://github.com/pskillen/meshflow-api/issues/275).

## Next phases

- **0.5:** ADRs (identity, channel, broadcast, dedup) informed by 0.4 data — [meshflow-api#276](https://github.com/pskillen/meshflow-api/issues/276).
- **1.x:** `MeshCorePacketSerializer` + `POST /api/meshcore/.../ingest/` and opt-in `MESHCORE_UPLOAD_ENABLED`.
