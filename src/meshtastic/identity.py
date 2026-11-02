"""Feeder identity: what the bot knows about its own Meshtastic radio.

In firmware 2.8 the node number becomes ``crc32(public key)``, so a feeder's
number can change on upgrade (or when a key is minted after the region is
set). The API identifies feeders by API key and uses the identity reported
here to notice and handle that change.

Only public, non-secret facts are read: the public key from the local node's
NodeDB ``user`` entry, the MAC from the same entry, firmware version from
device metadata, and the LoRa region / modem preset from the ``lora`` config
section. The ``security`` config section (which holds the private key) is
never touched.

Every field is ``None`` when the radio does not report it (a 2.7 node with no
key, a 2.8 node with no MAC, config not loaded yet); a missing value is
absent from the headers and payload, never an empty string.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

PUBKEY_HEADER = "X-Meshtastic-Feeder-Pubkey"
NODE_NUM_HEADER = "X-Meshtastic-Feeder-Node-Num"
FIRMWARE_HEADER = "X-Meshtastic-Feeder-Firmware"


@dataclass(frozen=True)
class FeederIdentity:
    """Snapshot of the local radio's identity. All fields optional."""

    node_num: Optional[int] = None
    """``my_node_num`` as an unsigned int."""

    pubkey: Optional[str] = None
    """Public key, base64 as the Meshtastic library reports it."""

    macaddr: Optional[str] = None
    """OTA MAC as lower-case colon-separated hex (``aa:bb:cc:dd:ee:ff``)."""

    firmware: Optional[str] = None
    """Firmware version string, e.g. ``2.7.11.abcdef0``."""

    region: Optional[str] = None
    """LoRa region code name, e.g. ``EU_868`` (``UNSET`` when not configured)."""

    preset: Optional[str] = None
    """Modem preset name, e.g. ``LONG_FAST``; absent when custom modem settings
    are in use (``use_preset`` false)."""

    def headers(self) -> dict[str, str]:
        """Request headers for Meshtastic API calls; only the fields we have."""
        headers: dict[str, str] = {}
        if self.pubkey:
            headers[PUBKEY_HEADER] = _header_safe(self.pubkey)
        if self.node_num is not None:
            headers[NODE_NUM_HEADER] = str(self.node_num)
        if self.firmware:
            headers[FIRMWARE_HEADER] = _header_safe(self.firmware)
        return {k: v for k, v in headers.items() if v}

    def bot_version_fields(self) -> dict[str, Any]:
        """Extra bot-version payload fields; only the fields we have."""
        fields = {
            "meshtastic_public_key": self.pubkey,
            "meshtastic_node_num": self.node_num,
            "meshtastic_firmware_version": self.firmware,
            "meshtastic_macaddr": self.macaddr,
            "meshtastic_region": self.region,
            "meshtastic_modem_preset": self.preset,
        }
        return {k: v for k, v in fields.items() if v is not None and v != ""}


def _header_safe(value: str) -> str:
    """HTTP header values must be latin-1 without control characters."""
    return "".join(c for c in str(value) if 32 <= ord(c) < 127).strip()


def read_node_num(interface: Any) -> Optional[int]:
    """The radio's current node number: ``myInfo.my_node_num``, else
    ``localNode.nodeNum``. ``None`` if neither is available yet."""
    my_info = getattr(interface, "myInfo", None)
    num = getattr(my_info, "my_node_num", None)
    if not num:
        num = getattr(getattr(interface, "localNode", None), "nodeNum", None)
    if isinstance(num, int) and not isinstance(num, bool) and num > 0:
        return num
    return None


def read_firmware_version(interface: Any) -> Optional[str]:
    """Firmware version from the device metadata the library collects during
    the config handshake (``interface.metadata``), else ``None``."""
    try:
        metadata = getattr(interface, "metadata", None)
        return getattr(metadata, "firmware_version", None) or None
    except Exception:
        return None


def _local_user(interface: Any) -> dict:
    try:
        user = interface.getMyUser()
    except Exception:
        return {}
    return user if isinstance(user, dict) else {}


def _read_pubkey(user: dict) -> Optional[str]:
    key = user.get("publicKey")
    if isinstance(key, (bytes, bytearray)):
        key = base64.b64encode(bytes(key)).decode("ascii")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return None


def _read_macaddr(user: dict) -> Optional[str]:
    mac = user.get("macaddr")
    if isinstance(mac, str) and ":" in mac:
        return mac.lower() or None
    raw: Optional[bytes] = None
    if isinstance(mac, (bytes, bytearray)):
        raw = bytes(mac)
    elif isinstance(mac, str) and mac.strip():
        try:
            raw = base64.b64decode(mac, validate=True)
        except (binascii.Error, ValueError):
            return None
    if not raw or not any(raw):
        return None
    return ":".join(f"{b:02x}" for b in raw)


def _enum_name(enum_type: Any, value: int) -> str:
    try:
        return enum_type.Name(value)
    except Exception:
        return f"UNKNOWN_{value}"


def _read_region_and_preset(interface: Any) -> tuple[Optional[str], Optional[str]]:
    """Region and preset from ``localNode.localConfig.lora``. Never reads the
    ``security`` section."""
    try:
        from meshtastic.protobuf import config_pb2

        local_config = interface.localNode.localConfig
        has_field = getattr(local_config, "HasField", None)
        if has_field is not None and not has_field("lora"):
            return None, None  # config not received yet; defaults would mislead
        lora = local_config.lora
        lora_type = config_pb2.Config.LoRaConfig
        region = _enum_name(lora_type.RegionCode, int(lora.region))
        preset = (
            _enum_name(lora_type.ModemPreset, int(lora.modem_preset))
            if lora.use_preset
            else None
        )
        return region, preset
    except Exception:
        return None, None


def read_identity(interface: Any) -> FeederIdentity:
    """Read the local radio's identity from a connected Meshtastic interface.

    Never raises; anything unreadable is left as ``None``."""
    user = _local_user(interface)
    region, preset = _read_region_and_preset(interface)
    return FeederIdentity(
        node_num=read_node_num(interface),
        pubkey=_read_pubkey(user),
        macaddr=_read_macaddr(user),
        firmware=read_firmware_version(interface),
        region=region,
        preset=preset,
    )
