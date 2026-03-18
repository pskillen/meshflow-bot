# Meshtastic Bot – Agent Context

Python bot for interacting with Meshtastic devices. Connects to a Meshtastic node over TCP, listens for messages, processes commands, and reports packets to the Meshflow API. Part of the Meshflow system alongside meshflow-api and meshtastic-bot-ui.

## Project Structure

```
src/
├── main.py                    # Entry point, env config, bot setup
├── bot.py                     # MeshtasticBot: pubsub handlers, connection, commands
├── tcp_interface.py           # AutoReconnectTcpInterface (Meshtastic TCP connection)
├── ws_client.py               # MeshflowWSClient – receives commands from API (e.g. traceroute)
├── traceroute.py              # Traceroute command (triggered via WebSocket)
├── data_classes.py            # MeshNode, packet data structures
├── helpers.py                 # pretty_print_last_heard, safe_encode_node_name, etc.
├── base_feature.py            # AbstractBaseFeature – reply_in_channel, message_in_dm, etc.
├── commands/                  # Text commands (!help, !nodes, !ping, etc.)
│   ├── factory.py             # CommandFactory – registers commands
│   ├── command.py             # AbstractCommand base class
│   ├── help.py, hello.py, nodes.py, ping.py, prefs.py, admin.py, template.py
│   └── enroll.py              # (commented out)
├── responders/                # Non-command message handlers
│   ├── responder_factory.py   # ResponderFactory
│   ├── responder.py           # AbstractResponder base class
│   └── message_reaction_responder.py
├── api/                       # Meshflow API integration
│   ├── StorageAPI.py          # StorageAPIWrapper – packet ingestion, node sync
│   ├── BaseAPIWrapper.py      # Base HTTP client
│   └── serializers.py         # MeshNodeSerializer
└── persistence/               # Local storage
    ├── node_db.py             # AbstractNodeDB, SqliteNodeDB
    ├── node_info.py           # AbstractNodeInfoStore, InMemoryNodeInfoStore
    ├── commands_logger.py     # AbstractCommandLogger, SqliteCommandLogger
    ├── user_prefs.py          # AbstractUserPrefsPersistence, SqliteUserPrefsPersistence
    └── packet_dump.py         # Packet dump utilities

test/                          # pytest unit tests
deploy/                        # Deployment scripts (Raspberry Pi, Docker)
```

## Key Concepts

- **MeshtasticBot**: Central class. Subscribes to pubsub (`meshtastic.receive`, `meshtastic.receive.text`, `meshtastic.node.updated`, `meshtastic.connection.established`). Owns interface, node_db, node_info, storage_apis, ws_client.
- **Commands**: Text messages starting with `!` (e.g. `!help`, `!nodes`). Registered in `CommandFactory`; extend `AbstractCommand`.
- **Responders**: Handle public channel messages without `!` prefix. Extend `AbstractResponder`.
- **StorageAPIWrapper**: Reports raw packets and node data to Meshflow API. Supports v1 and v2 API paths. Uses `STORAGE_API_*` or `STORAGE_API_2_*` env vars.
- **MeshflowWSClient**: Connects to `ws/nodes/?api_key=...` to receive remote commands (e.g. traceroute). Started after connection; uses same token as storage API.

## API Integration

- **Packet ingestion**: `StorageAPIWrapper` posts to `/api/packets/{my_nodenum}/ingest/` (v2) or `/api/raw-packet/` (v1).
- **Node sync**: `StorageAPIWrapper` fetches nodes from API for reconciliation.
- **WebSocket**: `MeshflowWSClient` connects to Meshflow API; receives JSON commands (e.g. `{"type": "traceroute", "target_node_id": 123}`). Invokes `on_traceroute_command` on the bot.

## Development

```bash
# activate venv
source venv/bin/activate

pip install -r requirements.txt
# Copy .env.example to .env and configure
python main.py
# or: python -m src.main (from project root)
```

## Testing

- **Unit tests**: `pytest test/ --doctest-modules`
- Tests live under `test/` (commands, persistence, responders, etc.)
- CI runs on Python 3.12, 3.13, 3.14

## Tech Stack

- Python 3.12+
- meshtastic (protobuf, TCP interface)
- Pypubsub (pub/sub events)
- requests (HTTP to Meshflow API)
- websockets (MeshflowWSClient)
- schedule (periodic tasks)
- pytest

## Configuration

Environment variables (see `.env.example`):

- `MESHTASTIC_IP` – Meshtastic node IP (TCP connection)
- `ADMIN_NODES` – Comma-separated node IDs (e.g. `!aae8900d`) for admin commands
- `STORAGE_API_ROOT`, `STORAGE_API_TOKEN`, `STORAGE_API_VERSION` – Primary Meshflow API
- `STORAGE_API_2_*` – Optional second API
- `MESHFLOW_WS_URL` – WebSocket URL (optional; derived from storage API if unset)
- `DATA_DIR` – Data directory (default `data/`)

## Conventions

- Commands: Add class to `src/commands/`, register in `CommandFactory.commands`.
- Responders: Add class to `src/responders/`, register in `ResponderFactory`.
- Use `reply_in_channel` / `reply_in_dm` from `AbstractBaseFeature`; avoid deprecated `reply` / `reply_to`.
- Node IDs: hex string format (e.g. `!12345678`). `my_nodenum` is decimal.
- Data persisted in `data/` (node_info.json, SQLite DBs, failed_packets).

## Source control

When asked to create a pull request description, follow the template at
.github/pull_request_template.md, and output a markdown file named `tmp/PR.md`
