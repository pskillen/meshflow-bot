import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file before anything else
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - [%(levelname)s] %(module)s.%(funcName)s - %(message)s',
                    stream=sys.stdout)

# Set the log level for specific modules
logging.getLogger('tcp_interface').setLevel(logging.WARNING)
logging.getLogger('stream_interface').setLevel(logging.WARNING)
logging.getLogger('mesh_interface').setLevel(logging.WARNING)

# Now we can import the rest of our local files
from src.api.StorageAPI import StorageAPIWrapper
from src.bot import MeshtasticBot
from src.helpers import get_env_bool
from src.ws_client import MeshflowWSClient
from src.persistence.commands_logger import SqliteCommandLogger
from src.persistence.node_info import InMemoryNodeInfoStore
from src.persistence.node_db import SqliteNodeDB
from src.persistence.user_prefs import SqliteUserPrefsPersistence
from src.tcp_proxy import TcpProxy

# Get the IP address and admin nodes from environment variables
MESHTASTIC_IP = os.getenv("MESHTASTIC_IP")
# Safely handle missing or empty ADMIN_NODES
admin_nodes_raw = os.getenv("ADMIN_NODES") or ""
ADMIN_NODES = [node.strip() for node in admin_nodes_raw.split(',') if node.strip()]

ENABLE_TCP_PROXY = get_env_bool("ENABLE_TCP_PROXY", True)
PROXY_HANDSHAKE_CACHE_SIZE = int(os.getenv("PROXY_HANDSHAKE_CACHE_SIZE", 100))
PROXY_ROLLING_CACHE_SIZE = int(os.getenv("PROXY_ROLLING_CACHE_SIZE", 100))

DATA_DIR = os.getenv("DATA_DIR", "data")
STORAGE_API_ROOT = os.getenv("STORAGE_API_ROOT")
STORAGE_API_TOKEN = os.getenv("STORAGE_API_TOKEN", None)
STORAGE_API_VERSION = int(os.getenv("STORAGE_API_VERSION", 1))
STORAGE_API_2_ROOT = os.getenv("STORAGE_API_2_ROOT")
STORAGE_API_2_TOKEN = os.getenv("STORAGE_API_2_TOKEN", None)
STORAGE_API_2_VERSION = int(os.getenv("STORAGE_API_2_VERSION", 1))
MESHFLOW_WS_URL = os.getenv("MESHFLOW_WS_URL")  # e.g. ws://localhost:8000; derived from storage API if unset

# Comma-separated portnums to skip when submitting to API (e.g. 345,ROUTING_APP)
_ignore_portnums_raw = os.getenv("IGNORE_PORTNUMS", "")
IGNORE_PORTNUMS = frozenset(
    p.strip().upper() for p in _ignore_portnums_raw.split(",") if p.strip()
)


def main():
    # Ensure data dir exists
    data_dir = os.path.join(Path(__file__).parent.parent, DATA_DIR)
    os.makedirs(data_dir, exist_ok=True)
    data_dir = Path(data_dir)
    user_prefs_file = data_dir / 'user_prefs.sqlite'
    command_log_file = data_dir / 'user_cmds.sqlite'
    node_db_file = data_dir / 'node_db.sqlite'
    node_info_file = data_dir / 'node_info.json'
    failed_packets_dir = data_dir / 'failed_packets'

    logging.info(f"--- Configuration ---")
    logging.info(f"MESHTASTIC_IP: {MESHTASTIC_IP}")
    logging.info(f"ENABLE_TCP_PROXY: {ENABLE_TCP_PROXY}")
    logging.info(f"PROXY_HANDSHAKE_CACHE_SIZE: {PROXY_HANDSHAKE_CACHE_SIZE}")
    logging.info(f"PROXY_ROLLING_CACHE_SIZE: {PROXY_ROLLING_CACHE_SIZE}")
    logging.info(f"ENABLE_FEATURE_NODE_TOTALS: {get_env_bool('ENABLE_FEATURE_NODE_TOTALS', True)}")
    logging.info(f"FREQUENCY_OF_NODE_REPORTS: {os.getenv('FREQUENCY_OF_NODE_REPORTS', '3')} hours")
    logging.info(f"CHANNEL_FOR_NODE_TOTAL_BROADCAST: {os.getenv('CHANNEL_FOR_NODE_TOTAL_BROADCAST', '2')}")
    logging.info(f"ENABLE_COMMAND_PING: {get_env_bool('ENABLE_COMMAND_PING', True)}")
    logging.info(f"ENABLE_COMMAND_TR: {get_env_bool('ENABLE_COMMAND_TR', True)}")
    logging.info(f"IGNORE_PORTNUMS: {list(IGNORE_PORTNUMS)}")
    logging.info(f"STORAGE_API_ROOT: {STORAGE_API_ROOT}")
    if STORAGE_API_2_ROOT:
        logging.info(f"STORAGE_API_2_ROOT: {STORAGE_API_2_ROOT}")
    logging.info(f"---------------------")

    proxy = None
    if ENABLE_TCP_PROXY:
        # Start the TCP Proxy
        # It listens on 0.0.0.0:4403 and forwards to MESHTASTIC_IP:4403
        proxy = TcpProxy(target_host=MESHTASTIC_IP, target_port=4403, listen_host='0.0.0.0', listen_port=4403, handshake_cache_size=PROXY_HANDSHAKE_CACHE_SIZE, rolling_cache_size=PROXY_ROLLING_CACHE_SIZE)
        proxy.start()
        
        # Give the proxy a moment to bind to the port before the bot tries to connect
        time.sleep(2)

    # Connect to the Meshtastic node
    # Use 'localhost' if proxy is enabled, otherwise connect directly
    connection_address = 'localhost' if ENABLE_TCP_PROXY else MESHTASTIC_IP
    bot = MeshtasticBot(connection_address)
    bot.proxy = proxy
    bot.ignore_portnums = IGNORE_PORTNUMS
    bot.admin_nodes = ADMIN_NODES
    bot.user_prefs_persistence = SqliteUserPrefsPersistence(str(user_prefs_file))
    bot.command_logger = SqliteCommandLogger(str(command_log_file))
    bot.node_db = SqliteNodeDB(str(node_db_file))
    node_info = InMemoryNodeInfoStore()
    bot.node_info = node_info
    if STORAGE_API_ROOT:
        bot.storage_apis.append(StorageAPIWrapper(bot, STORAGE_API_ROOT, STORAGE_API_TOKEN, STORAGE_API_VERSION, failed_packets_dir))
    if STORAGE_API_2_ROOT:
        bot.storage_apis.append(StorageAPIWrapper(bot, STORAGE_API_2_ROOT, STORAGE_API_2_TOKEN, STORAGE_API_2_VERSION, failed_packets_dir))

    # WebSocket client for receiving commands (e.g. traceroute)
    ws_url = MESHFLOW_WS_URL
    ws_token = None
    if not ws_url:
        base = STORAGE_API_ROOT
        if base:
            ws_url = base \
                .replace("http://", "ws://") \
                .replace("https://", "wss://")
    if STORAGE_API_ROOT and STORAGE_API_TOKEN:
        ws_token = STORAGE_API_TOKEN
    if ws_url and ws_token:
        bot.ws_client = MeshflowWSClient(
            ws_url=ws_url,
            api_key=ws_token,
            on_traceroute=bot.on_traceroute_command,
        )

    try:
        node_info.load_from_file(str(node_info_file))
        bot.connect()
        bot.start_scheduler()

    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        if bot.ws_client:
            bot.ws_client.stop()
        bot.disconnect()
        node_info.persist_to_file(str(node_info_file))


if __name__ == "__main__":
    main()
