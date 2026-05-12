# Meshtastic

[Meshtastic](https://meshtastic.org) is an open LoRa mesh firmware ecosystem. Meshflow Bot speaks to a node over **TCP** using the official [`meshtastic`](https://pypi.org/project/meshtastic/) Python library. The adapter lives under [`src/meshtastic/`](../src/meshtastic/).

## Connection

| Variable | Description |
|----------|-------------|
| `RADIO_PROTOCOL` | Use `meshtastic` (default) or omit (defaults to Meshtastic). |
| `MESHTASTIC_IP` | Hostname or IP of the node’s TCP API (required for Meshtastic mode). |

The concrete radio implementation is `MeshtasticRadio` in [`src/meshtastic/radio.py`](../src/meshtastic/radio.py) (auto-reconnect TCP, pubsub, packet translation).

## Meshflow API upload

When `STORAGE_API_ROOT` is set and `RADIO_PROTOCOL=meshtastic`:

- **v2:** `POST /api/packets/{my_nodenum}/ingest/` for raw packets.
- **v1:** `POST /api/raw-packet/`.

| Variable | Description |
|----------|-------------|
| `STORAGE_API_ROOT` | Base URL of meshflow-api |
| `STORAGE_API_TOKEN` | Bearer / API token |
| `STORAGE_API_VERSION` | `1` or `2` |
| `STORAGE_API_2_*` | Optional second destination |

Failed uploads can be retained under `data/failed_packets/` when configured.

## WebSocket commands

With `MESHFLOW_WS_URL` + token (or derived from `STORAGE_API_*`), the bot starts `MeshflowWSClient` for remote actions such as **traceroute** after the radio connects.

## Optional behaviour

| Variable | Description |
|----------|-------------|
| `IGNORE_PORTNUMS` | Comma-separated portnums to skip when uploading (upper-case, e.g. `ROUTING_APP`). |
| `DUMP_PACKETS_PORTNUMS` | Comma-separated Meshtastic `portnum` names (or `*`) to mirror received packets as JSON under `data/packets/<PORTNUM>/`. See [`src/persistence/packet_dump.py`](../src/persistence/packet_dump.py). |
| `ADMIN_NODES` | Comma-separated `!hex8` node ids allowed to run admin commands. |
| `DATA_DIR` | Data root (default `data/`). |

## Sample packet JSON

Example Meshtastic-shaped packets for tests/docs live under [`docs/packets/`](packets/) (encrypted, nodeinfo, position, routing, telemetry, text).

## Running

```bash
source venv/bin/activate
export RADIO_PROTOCOL=meshtastic   # optional; this is the default
export MESHTASTIC_IP=192.168.1.50
export STORAGE_API_ROOT=https://api.example.com
export STORAGE_API_TOKEN=...
export STORAGE_API_VERSION=2
python -m src.main
```

Docker: use the `meshflow-bot-meshtastic` service in [`docker-compose.yaml`](../docker-compose.yaml).

## See also

- [MeshCore capture mode](MESHCORE.md) — second protocol, USB/BLE, no API upload in Phase 0.3.
