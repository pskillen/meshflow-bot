# Meshflow Bot

Meshflow Bot is a Python bot that connects to **mesh radios** and integrates with [meshflow-api](https://github.com/pskillen/meshflow-api). It listens for traffic, handles `!` commands, optional responders, and (for Meshtastic) uploads packets to the API.

**Protocols**

- **[Meshtastic](docs/MESHTASTIC.md)** — TCP to a Meshtastic node; full API upload + WebSocket traceroute today.
- **[MeshCore](docs/MESHCORE.md)** — USB serial or BLE via [`meshcore`](https://github.com/meshcore-dev/meshcore_py); **Phase 0.3** adds capture-only connectivity (JSON dumps under `data/meshcore_packets/`, no API ingest yet).

Select the radio with `RADIO_PROTOCOL=meshtastic` (default) or `RADIO_PROTOCOL=meshcore`. See the linked docs for environment variables.

## Quick Start: Run with Docker

The easiest way to run the bot is Docker Compose. Two services are defined: `meshflow-bot-meshtastic` and `meshflow-bot-meshcore` (adjust devices, env, and image tags for your environment).

### 1. Prepare Your Environment

- Ensure you have [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed.
- Create a `.env` file in the project directory (see [`.env.example`](.env.example)).

### 2. Use `docker-compose.yaml`

From the repo root:

```sh
docker compose up -d meshflow-bot-meshtastic
# or, for MeshCore over USB (Linux device pass-through):
docker compose up -d meshflow-bot-meshcore
```

Images are published as `ghcr.io/pskillen/meshflow-bot` (the legacy `meshtastic-bot` image name is deprecated).

### 3. Data directories

- Meshtastic service mounts `./data`.
- MeshCore service mounts `./data-meshcore` so captures do not clash with the MT bot.

---

## Native Installation (Advanced/Development)

1. **Clone the repository:**
    ```sh
    git clone https://github.com/pskillen/meshflow-bot.git
    cd meshflow-bot
    ```
2. **Install dependencies:**
    ```sh
    pip install -r requirements.txt
    ```
3. **(Optional) On Raspberry Pi:**
    ```sh
    sudo apt-get install libopenblas-dev
    ```
4. **Configure environment:**
    - Copy `.env.example` to `.env` and fill in the required values (see [Meshtastic](docs/MESHTASTIC.md) / [MeshCore](docs/MESHCORE.md)).
5. **Run the bot:**
    ```sh
    python -m src.main
    ```

---

## Usage

The bot listens for traffic and responds to `!` commands where the underlying protocol exposes text (Meshtastic today; MeshCore in capture mode still runs command dispatch for local testing).

### Supported Commands

| Command   | Description                                    |
|-----------|------------------------------------------------|
| `!help`   | Displays a list of available commands          |
| `!hello`  | Displays information about the bot             |
| `!ping`   | Responds with "Pong!"                          |
| `!nodes`  | Displays a list of connected nodes, stats, etc |
| `!whoami` | Displays information about the sender          |

---

## Extending the Bot (Development)

If you want to add new commands or responders, see the `src/commands/` and `src/responders/` directories. The codebase is structured for easy extension, but most users will not need to modify the code to run the bot.

- **Commands:** Add new command classes and register them in the command factory.
- **Responders:** Inherit from `AbstractResponder` to handle public channel messages.

---

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License.
