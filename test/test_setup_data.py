import random
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from src.data_classes import MeshNode
from src.persistence.node_db import InMemoryNodeDB
from src.persistence.node_info import InMemoryNodeInfoStore
from src.radio.events import IncomingTextMessage


def meshtastic_id_to_hex(meshtastic_id: int) -> str:
    """Convert a Meshtastic ID (integer form) to hex representation (!abcdef12)."""
    return f"!{meshtastic_id:08x}"


def meshtastic_hex_to_int(node_id: str) -> int:
    """Convert a Meshtastic ID (hex representation) to integer form."""
    return int(node_id[1:], 16)


def generate_random_snr():
    return random.uniform(-20, 20)


def generate_random_rssi():
    return random.uniform(-100, 0)


def generate_random_packet_id():
    return random.randint(0, 2 ** 32 - 1)  # 32-bit unsigned int


_packet_types = [
    'TEXT_MESSAGE_APP',
    'POSITION_APP',
    'TRACKER_APP',
    'PRIVATE_APP',
    'BROADCAST_APP',
]


def generate_random_packet_type() -> str:
    return random.choice(_packet_types)


def random_node_id():
    return random.randint(0, 2 ** 32 - 1)  # 32-bit unsigned int


def random_node_id_hex():
    return meshtastic_id_to_hex(random_node_id())


def make_node():
    node = MeshNode()
    node.user = MeshNode.User()
    node.user.id = random_node_id_hex()
    node.user.short_name = node.user.id[-4:]
    node.user.long_name = 'Node ' + node.user.id
    return node


def get_test_bot(node_count=2, admin_node_count=1):
    """Build a :class:`MeshflowBot` with a :class:`FakeRadio`, mocked
    persistence, and some random nodes.

    Returns the bot, a list of non-admin nodes, and a list of admin nodes.
    """
    from src.bot import MeshflowBot
    from test.fake_radio import FakeRadio

    nodes: list[MeshNode] = [make_node() for _ in range(node_count)]
    admin_nodes: list[MeshNode] = [make_node() for _ in range(admin_node_count)]
    all_nodes = nodes + admin_nodes

    fake_radio = FakeRadio(local_node_id=nodes[0].user.id, local_nodenum=meshtastic_hex_to_int(nodes[0].user.id))
    bot = MeshflowBot(radio=fake_radio)
    bot.admin_nodes = [node.user.id for node in admin_nodes]

    bot.node_db = InMemoryNodeDB()
    bot.node_info = InMemoryNodeInfoStore()
    bot.command_logger = Mock()
    bot.user_prefs_persistence = Mock()

    for node in all_nodes:
        last_heard_mins_ago = random.randint(0, 180)
        last_heard = datetime.now(timezone.utc) - timedelta(minutes=last_heard_mins_ago)

        bot.node_db.store_node(node)
        for _ in range(random.randint(1, 10)):
            bot.node_info.node_packet_received(node.user.id, generate_random_packet_type())
        bot.node_info.update_last_heard(node.user.id, last_heard)

    return bot, nodes, admin_nodes


def build_test_text_message(
    text: str,
    sender_id: str = None,
    to_id: str = None,
    *,
    max_hops: int = 6,
    hops_left: int = 3,
    channel: int = 0,
    is_dm: bool = True,
    message_id: int = None,
) -> IncomingTextMessage:
    """Build a synthetic :class:`IncomingTextMessage` for tests.

    By default the message looks like a DM (``is_dm=True``); pass ``is_dm=False``
    for public channel messages.
    """
    sender_id = sender_id or random_node_id_hex()
    to_id = to_id or random_node_id_hex()
    return IncomingTextMessage(
        text=text,
        from_id=sender_id,
        to_id=to_id,
        channel=channel,
        message_id=message_id if message_id is not None else generate_random_packet_id(),
        hop_start=max_hops,
        hop_limit=hops_left,
        is_dm=is_dm,
    )


# Backward-compatible alias retained for tests still using the old name.
# The shape returned now is an :class:`IncomingTextMessage`, not a dict, so
# any test that subscripts the result needs updating.
def build_test_text_packet(*args, **kwargs) -> IncomingTextMessage:
    return build_test_text_message(*args, **kwargs)
