# MeshCore (Phase 0.3 — capture-only)

[MeshCore](https://meshcore.co.uk) is a mesh radio protocol and companion firmware family. This bot integrates via the [`meshcore` PyPI package](https://github.com/meshcore-dev/meshcore_py) (Python bindings).

**Phase 0.3 scope:** connect, receive events, translate them into the bot’s generic `RadioInterface` events, and write JSON captures under `data/meshcore_packets/<event_type>/`.

**Phase 1 upload:** when `MESHCORE_UPLOAD_ENABLED=true` and `STORAGE_API_*` are set, selected events upload to `POST /api/meshcore/feeders/{prefix}/packets/ingest/` (12-hex pubkey prefix from `SELF_INFO`).

On first connect the bot sends one **flood-routed advert** (`send_advert(flood=True)`), then repeats on a schedule from the API: `ManagedNode.mc_flood_advert_interval_hours` (default **6h**, range **2–24h**), fetched via `GET /api/meshcore/feeders/{prefix}/bot-config/` when `MESHCORE_UPLOAD_ENABLED` is set. Operators change the interval in the API; the bot picks it up on reconnect or immediately via WebSocket `refresh_feeder_config` ([#116](https://github.com/pskillen/meshflow-bot/issues/116)).

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

Without `MESHCORE_UPLOAD_ENABLED`, `STORAGE_API_*` is ignored.

## Channel sync and WebSocket (Phase 2.2)

When `MESHCORE_UPLOAD_ENABLED=true` and `STORAGE_API_*` are set, the bot also:

1. **On connect** — reads the device channel table once (`meshcore.commands.get_channel`) and `POST`s the same snapshot to `/api/meshcore/feeders/{prefix}/mc-channel-sync/` on **each** configured API (`STORAGE_API_ROOT` and optional `STORAGE_API_2_ROOT` when `MESHCORE_UPLOAD_ENABLED=true`). Uses `STORAGE_API_2_TOKEN` if set, otherwise the primary `STORAGE_API_TOKEN`.
2. **WebSocket** — connects to `ws/nodes/?api_key=…` (URL derived from `STORAGE_API_ROOT` when `MESHFLOW_WS_URL` is unset). MeshCore feeders automatically append `feeder_pubkey_prefix` from the device pubkey after connect (no env var). Used for UI **apply to radio** (`apply_mc_channel_config`): the REST endpoint only dispatches to the bot over WS; the bot **clears any device slot not in the apply payload**, writes each listed slot via `set_channel`, then re-syncs to the API ([#130](https://github.com/pskillen/meshflow-bot/issues/130)).

Traceroute commands remain Meshtastic-only; MC feeders ignore `traceroute` WS messages.

## Meshflow upload event types

| `event_type` (capture / wire) | Upload | GPS / name in API |
|------------------------------|--------|-------------------|
| `advertisement` | Yes (`payload_type: advert`) | Identity only (`public_key`) |
| **`rx_log_data`** + `payload_typename: ADVERT` | Yes | **`adv_lat` / `adv_lon` / `adv_name`** (map coordinates in Meshflow UI) |
| `contact_message`, `channel_message` | Yes (text) | N/A |
| `rx_log_data` + `TEXT_MSG` or `PATH` | Yes (`payload_type: raw`) | Path + `pkt_hash` for API twin-merge to channel messages |
| `rx_log_data` (REQ, CONTROL, …) | No (`MeshCoreSkipUpload`) | N/A |

Map coordinates in the Meshflow UI require **bot** [meshflow-bot#102](https://github.com/pskillen/meshflow-bot/issues/102) and **API** [meshflow-api#330](https://github.com/pskillen/meshflow-api/issues/330) / [#298](https://github.com/pskillen/meshflow-api/issues/298) deployed on feeders.

## Claiming a node (ownership proof)

Meshflow users claim MeshCore observed nodes the same way as Meshtastic: the UI shows a **claim key**; you prove ownership by sending that key from **your** radio to a **MeshCore feeder** already in the system.

1. In the Meshflow UI, open your observed node → **Claim Node** → copy the claim key.
2. On your MeshCore device, open a **contact/DM** to a known MeshCore feeder (not a channel/broadcast message).
3. Send a message whose body is **only** the claim key (no extra text).
4. The feeder bot must have `MESHCORE_UPLOAD_ENABLED=true` and upload `contact_message` as `contact_text` (default in Phase 1+).
5. The UI should show success within a second via WebSocket; otherwise wait for the slow status poll.

The feeder only needs to **receive** your DM; you do not need to operate the feeder yourself. See meshflow-api [node-claims-meshcore.md](https://github.com/pskillen/meshflow-api/blob/main/docs/features/node-lifecycle/node-claims-meshcore.md).

## Local identity

MeshCore nodes are identified by **Ed25519 public keys** (64 hex chars), not Meshtastic-style 32-bit node numbers.

- `MeshCoreRadio.local_node_id` is `mc:` + the first **12** hex characters of the companion’s public key after `SELF_INFO` (or `mc:unknown` if that event is missing).
- `feeder_mc_pubkey` (64 hex) and `feeder_mc_pubkey_prefix` (12 hex) are sent on all MeshCore API calls: URL prefix plus optional header `X-MeshCore-Feeder-Pubkey`. Configure the same full pubkey on `ManagedNode.mc_pubkey` in Django admin (see meshflow-api `docs/features/meshcore/feeder-bootstrap.md`).
- `local_nodenum` is `None` for MeshCore; do not use `/api/packets/0/bot-version/`. Bot version uses `PUT /api/meshcore/feeders/{prefix}/bot-version/`.

Remote senders in DMs use ids like `mc:p:<12-hex-prefix>` when only a short prefix is on the wire.

## Running (local)

```bash
source venv/bin/activate
export RADIO_PROTOCOL=meshcore
export MESHCORE_SERIAL_DEVICE=/dev/ttyUSB0
# Required for API upload + channel sync (Phase 1+):
export MESHCORE_UPLOAD_ENABLED=true
export STORAGE_API_ROOT=http://localhost:8000/api
export STORAGE_API_TOKEN=<your Node API key>
export STORAGE_API_VERSION=2
python -m src.main
```

After connect, confirm logs show `POST /api/meshcore/feeders/{12-hex-prefix}/packets/ingest/` and `.../mc-channel-sync/`. Do **not** point MeshCore at `/api/packets/0/ingest/` or `/api/packets/0/bot-version/`.

Operator setup (Django `ManagedNode`, `mc_pubkey`, API key): **[meshflow-api feeder bootstrap](https://github.com/pskillen/meshflow-api/blob/main/docs/features/meshcore/feeder-bootstrap.md)**.

## Docker Compose

Use the **`meshflow-bot-meshcore`** service in [`docker-compose.yaml`](../docker-compose.yaml). Example overrides (create `.env` beside compose or set under `environment:`):

| Variable | Example | Notes |
|----------|---------|--------|
| `RADIO_PROTOCOL` | `meshcore` | Required |
| `MESHCORE_SERIAL_DEVICE` | `/dev/ttyUSB0` | **Or** `MESHCORE_BLE_ADDRESS` (not both) |
| `MESHCORE_UPLOAD_ENABLED` | `true` | Without this, `STORAGE_API_*` is ignored |
| `STORAGE_API_ROOT` | `http://host.docker.internal:8000/api` | Reachable API base (include `/api`) |
| `STORAGE_API_TOKEN` | `<Node API key>` | From Meshflow admin |
| `STORAGE_API_VERSION` | `2` | Match your API |
| `ADMIN_NODES` | `mc:deadbeefcafe` | Optional; MC admin id format may evolve |

The compose file maps `/dev/ttyUSB0` into the container (Linux host). Adjust the device path or use BLE env vars on macOS/Windows. Data captures go to `./data-meshcore` → `/app/data`.

**Smoke test:** with API + bot running, watch ingest logs, then in Meshflow UI open **MeshCore → Nodes** (map) and **MeshCore → Messages** after channel sync.

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
