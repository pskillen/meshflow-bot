# Meshflow Bot – Agent Context

Python bot for mesh radios: **Meshtastic** (TCP) and **MeshCore** (USB serial / BLE). Connects to a device, listens for messages, runs commands/responders, and (Meshtastic only) reports packets to meshflow-api. Part of the Meshflow system alongside meshflow-api and meshflow-ui.

Protocol is selected at runtime with **`RADIO_PROTOCOL`** (`meshtastic` default, or `meshcore`). Adapters implement `RadioInterface` in [`src/radio/interface.py`](src/radio/interface.py).

## Project Structure

```
src/
├── main.py                 # Entry: build_radio(), StorageAPI / WS wiring
├── bot.py                  # MeshflowBot (protocol-agnostic core)
├── radio/                  # RadioInterface + shared events/errors
├── meshtastic/             # MeshtasticRadio, TCP, translation, serializers
├── meshcore/               # MeshCoreRadio (asyncio thread), translation, dump, serializers stub
├── ws_client.py            # MeshflowWSClient (Meshtastic traceroute commands)
├── data_classes.py         # MeshNode, shared models
├── helpers.py
├── base_feature.py
├── commands/
├── responders/
├── api/                    # StorageAPIWrapper, serializers base
└── persistence/

docs/
├── MESHTASTIC.md           # Meshtastic env + behaviour
├── MESHCORE.md             # MeshCore capture-only (Phase 0.3)
└── packets/                # Sample Meshtastic JSON fixtures

test/
deploy/
```

## Key Concepts

- **MeshflowBot** ([`src/bot.py`](src/bot.py)): Registers `RadioHandlers` on the active `RadioInterface`; scheduling, commands, responders, persistence, optional `StorageAPIWrapper` + `MeshflowWSClient`.
- **MeshtasticRadio** ([`src/meshtastic/radio.py`](src/meshtastic/radio.py)): TCP + pubsub; translates to `IncomingPacket` / `IncomingTextMessage` / `NodeUpdate`.
- **MeshCoreRadio** ([`src/meshcore/radio.py`](src/meshcore/radio.py)): Runs `meshcore` on a dedicated asyncio loop in a thread; dumps JSON to `data/meshcore_packets/`; Phase 0.3 **no** API upload.
- **Commands / responders**: Same as before; extend `AbstractCommand` / `AbstractResponder`.
- **StorageAPIWrapper**: Used when `RADIO_PROTOCOL=meshtastic` and `STORAGE_API_ROOT` is set.
- **MeshflowWSClient**: Started only for `RADIO_PROTOCOL=meshtastic` when WS URL + token are configured.

## API Integration (Meshtastic)

- **Packet ingestion**: v2 `POST /api/packets/{my_nodenum}/ingest/`, v1 `/api/raw-packet/`.
- **Node sync**: `StorageAPIWrapper` node endpoints.
- **WebSocket**: remote traceroute and similar commands.

## Development

```bash
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

## Testing

- **Unit tests**: `pytest test/ --doctest-modules`
- CI runs on Python 3.12, 3.13, 3.14

## Tech Stack

- Python 3.12+
- meshtastic, meshcore (PyPI), Pypubsub, requests, websockets, schedule, pytest

## Configuration

See [`.env.example`](.env.example), [docs/MESHTASTIC.md](docs/MESHTASTIC.md), and [docs/MESHCORE.md](docs/MESHCORE.md).

## Conventions

- Commands: `src/commands/`, register in `CommandFactory`.
- Responders: `src/responders/`, register in `ResponderFactory`.
- Use `reply_in_channel` / `reply_in_dm` from `AbstractBaseFeature`.
- Meshtastic node IDs: `!` + 8 hex nibbles; `my_nodenum` is decimal.
- MeshCore: pubkey-based ids (`mc:...`); `my_nodenum` is `None` for MC.

## Source control

When asked to create a pull request description, follow the template at
`.github/pull_request_template.md`, and output a markdown file named `tmp/PR.md`

## Plan mode

When creating a plan, Include that we should branch from the latest origin/main, do the work, commit, push, and open a PR. Use the github-personal MCP. the gh
command is not available, do not use it.
