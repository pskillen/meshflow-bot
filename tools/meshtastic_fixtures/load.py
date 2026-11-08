"""Load the committed Meshtastic packet fixtures. Standard library only.

The api repo's CI imports this module (bot root on ``sys.path``) and nothing
else from ``tools/``; keep it free of third-party imports.

>>> lib_packet({"record": {"packet": {"from": 1, "channel": 2}}})["raw"].channel
2
"""

from __future__ import annotations

import copy
import json
import types
from pathlib import Path


def load_subset(root: Path) -> list[dict]:
    """The labelled subset (``<root>/subset.json``); *root* is ``docs/meshtastic_packets/2.8``."""
    return json.loads((Path(root) / "subset.json").read_text(encoding="utf-8"))


def lib_packet(entry: dict) -> dict:
    """The dict the radio callback hands the bot for this subset entry.

    ``raw`` is a stand-in for the protobuf the live library attaches: only
    ``channel`` is read off it (the serialiser copies it when the dict lacks one).
    """
    packet = copy.deepcopy(entry["record"]["packet"])
    packet["raw"] = types.SimpleNamespace(channel=packet.get("channel", 0))
    return packet
