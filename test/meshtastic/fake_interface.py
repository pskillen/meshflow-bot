"""A fake connected Meshtastic interface for identity tests.

Shaped like the library's ``MeshInterface``: ``myInfo.my_node_num``,
``localNode.nodeNum`` / ``localNode.localConfig`` (a real ``LocalConfig``),
``metadata.firmware_version`` and ``getMyUser()`` backed by ``nodesByNum``.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Optional

from meshtastic.protobuf import config_pb2, localonly_pb2

PUBKEY_BYTES = bytes(range(1, 33))
PUBKEY_B64 = base64.b64encode(PUBKEY_BYTES).decode()
MAC_BYTES = bytes.fromhex("a1b2c3d4e5f6")
MAC_B64 = base64.b64encode(MAC_BYTES).decode()


class FakeInterface:
    def __init__(
        self,
        node_num: int = 0x11223344,
        *,
        pubkey_b64: Optional[str] = PUBKEY_B64,
        macaddr_b64: Optional[str] = MAC_B64,
        firmware: Optional[str] = "2.7.11.abcdef0",
        region: Optional[int] = config_pb2.Config.LoRaConfig.EU_868,
        use_preset: bool = True,
        preset: int = config_pb2.Config.LoRaConfig.LONG_FAST,
        lora_config_received: bool = True,
    ):
        self.myInfo = SimpleNamespace(my_node_num=node_num)
        self.localNode = SimpleNamespace(
            nodeNum=node_num, localConfig=localonly_pb2.LocalConfig()
        )
        self.metadata = (
            SimpleNamespace(firmware_version=firmware) if firmware is not None else None
        )
        self.nodesByNum: dict = {}
        self.nodes: dict = {}
        self.set_user(pubkey_b64=pubkey_b64, macaddr_b64=macaddr_b64)
        if lora_config_received:
            lora = self.localNode.localConfig.lora
            lora.use_preset = use_preset
            lora.modem_preset = preset
            if region is not None:
                lora.region = region
            else:
                lora.hop_limit = 3  # mark the section present, region UNSET

    def set_user(self, *, pubkey_b64, macaddr_b64) -> None:
        user: dict = {"id": "!11223344", "longName": "Feeder"}
        if pubkey_b64 is not None:
            user["publicKey"] = pubkey_b64
        if macaddr_b64 is not None:
            user["macaddr"] = macaddr_b64
        num = self.myInfo.my_node_num
        self.nodesByNum = {num: {"num": num, "user": user}}

    def change_node_num(self, new_num: int, *, new_pubkey_b64: Optional[str] = None):
        """What a 2.8 radio does when a key is minted: new number, new key."""
        user = dict(self.nodesByNum[self.myInfo.my_node_num]["user"])
        if new_pubkey_b64 is not None:
            user["publicKey"] = new_pubkey_b64
        self.myInfo = SimpleNamespace(my_node_num=new_num)
        self.localNode.nodeNum = new_num
        self.nodesByNum = {new_num: {"num": new_num, "user": user}}

    def getMyUser(self):
        node = self.nodesByNum.get(self.myInfo.my_node_num)
        return node.get("user") if node else None
