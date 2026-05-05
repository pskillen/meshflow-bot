# Meshflow Bot

Meshflow Bot is a Python-based bot for interacting with Meshtastic devices. It listens for messages, processes commands, and responds with appropriate actions. This guide is focused on helping you run the bot as-is, with minimal setup.

## Quick Start: Run with Docker

The easiest way to run Meshtastic Bot is using Docker. This method requires minimal setup and keeps your environment clean.

### 1. Prepare Your Environment

- Ensure you have [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed.
- Create a `.env` file in your project directory with the required environment variables:

```
MESHTASTIC_NODE_IP=your_meshtastic_node_ip
ADMIN_NODES=comma_separated_admin_node_ids
STORAGE_API_ROOT=your_storage_api_url
STORAGE_API_TOKEN=your_storage_api_token
# Optionally, you can upload to a second API as well
STORAGE_API_2_ROOT=your_storage_api_2_url
STORAGE_API_2_TOKEN=your_storage_api_2_token
```

### 2. Use This `docker-compose.yaml`

```yaml
version: '3.8'

services:
  bot:
    image: ghcr.io/pskillen/meshflow-bot:latest
    container_name: meshflow-bot
    # Note: the legacy image name ghcr.io/pskillen/meshtastic-bot is deprecated
    # and will be removed in a future release. Please update to meshflow-bot.
    restart: unless-stopped
    environment:
      - MESHTASTIC_IP=${MESHTASTIC_NODE_IP}
      - ADMIN_NODES=${ADMIN_NODES}
      - STORAGE_API_ROOT=${STORAGE_API_ROOT}
      - STORAGE_API_TOKEN=${STORAGE_API_TOKEN}
      - STORAGE_API_VERSION=2
      - STORAGE_API_2_ROOT=${STORAGE_API_2_ROOT}
      - STORAGE_API_2_TOKEN=${STORAGE_API_2_TOKEN}
      - STORAGE_API_2_VERSION=2
    volumes:
      - mesh_bot_data:/app/data

volumes:
  mesh_bot_data:
```

### 3. Start the Bot

```sh
docker compose up -d
```

The bot will now run in the background. Data will be persisted locally in the `mesh_bot_data` Docker volume.

---

## Native Installation (Advanced/Development)

If you prefer to run the bot natively (e.g., for development or customization):

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
    - Copy `.env.example` to `.env` and fill in the required values.
5. **Run the bot:**
    ```sh
    python main.py
    ```

---

## Usage

The bot listens for messages and responds to commands. You can interact with it via supported Meshtastic channels.

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
