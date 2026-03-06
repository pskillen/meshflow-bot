# Meshtastic Bot

Meshtastic Bot is a Python-based bot for interacting with Meshtastic devices. It listens for messages, processes commands, and responds with appropriate actions. This guide is focused on helping you run the bot as-is, with minimal setup.

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
    image: ghcr.io/pskillen/meshtastic-bot:latest
    container_name: meshtastic-bot
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

## Customization

You can enable or disable specific features and commands using environment variables in your `.env` or `meshtastic-bot.env` file. All options default to `true` if not specified.

### Feature Toggles
- `ENABLE_TCP_PROXY`: Set to `false` to disable the internal TCP proxy. The bot will connect directly to `MESHTASTIC_IP`.

### Command Toggles
Set any of the following to `false` to disable the command and hide it from the `!help` menu:
- `ENABLE_COMMAND_PING`
- `ENABLE_COMMAND_TR`
- `ENABLE_COMMAND_HELLO`
- `ENABLE_COMMAND_HELP`
- `ENABLE_COMMAND_NODES`
- `ENABLE_COMMAND_WHOAMI`
- `ENABLE_COMMAND_PREFS`
- `ENABLE_COMMAND_ADMIN`
- `ENABLE_COMMAND_STATUS`

---

## Docker Compose Options

There are two primary ways to run the bot using Docker:

### 1. Standard (`docker-compose.yaml`) - **Recommended for local builds**
- **Purpose**: Stable use with local source control.
- **How it works**: It builds the bot locally from the source files in the repository.
- **Includes**: Integrated **Watchtower** service which automatically checks for and applies updates to the `meshtastic-bot` container every hour.
- **Environment**: Configuration is pulled from your `.env` file.

### 2. Remote/Pre-built (`docker-compose-remote.yaml`)
- **Purpose**: Quick deployment using the official container.
- **How it works**: Pulls the pre-built image from the **GitHub Container Registry** (`ghcr.io`). 
- **Configuration**: Uses `meshtastic-bot.env` for environment variables and a named Docker volume (`mesh_bot_data`) for persistence.

---

## Native Installation (Advanced/Development)

If you prefer to run the bot natively (e.g., for development or customization):

1. **Clone the repository:**
    ```sh
    git clone https://github.com/yourusername/meshtastic-bot.git
    cd meshtastic-bot
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

| Command   | Description                                                   |
|-----------|---------------------------------------------------------------|
| `!help`   | Displays a list of available commands                         |
| `!hello`  | Displays information about the bot                            |
| `!ping`   | Responds with "Pong!"                                         |
| `!nodes busy` | Displays a summary of the busiest nodes             |
| `!whoami` | Displays information about the sender                         |
| `!tr`     | Performs a traceroute to the sender (outbound & inbound)      |
| `!tr <shortname>` | Performs a traceroute to a specific node by its short name from management node (outbound & inbound) |
| `!status` | Displays bot status and radio connection details              |

## Features

### Usage Statistics
- **Busy Nodes:** Use `!nodes busy` to see a summary of the most active nodes on your mesh.
- **Detailed Stats:** Use `!nodes busy detailed` for an in-depth breakdown of packet types for those busiest nodes.
- **Specific Node:** Use `!nodes busy <shortname>` to see stats for a particular node.

### Enhanced Connectivity (TCP Proxy)
The bot now includes a built-in TCP proxy to manage the connection to the Meshtastic node. This improves stability and allows for automatic reconnection if the radio connection is lost.

### Improved Logging
Messages received on named Group Channels (e.g., 'LongRange', 'PrivateChat') are now logged with their specific channel name, making it easier to track conversations across different mesh networks.

**Log Format Details:**
The bot uses emojis and badges in its standard output logs to easily identify incoming requests:
- **Private Messages**: `✉️  [PRIVATE MSG]`
- **Group Messages**: `📢 [GROUP MSG]`
- **Bot Commands**: `🤖 [BOT CMD]`
- **Responder Actions**: `🤖 [RESPONDER]`

### Advanced Traceroute
The `!tr` command provides visibility into the mesh topology:
- **Full Path visibility:** Shows the complete route including the target node.
- **Targeted Trace:** Use `!tr <shortname>` (e.g., `!tr NUMC`) to trace the route to a specific node. The results will be sent back to you.
- **Outbound:** The route from the bot to the destination.
- **Inbound:** The route back from the destination to the bot (if available).

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
