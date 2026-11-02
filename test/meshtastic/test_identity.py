"""Reading the feeder identity from a (fake) 2.7- or 2.8-shaped interface."""

import base64

from meshtastic.protobuf import config_pb2

from src.meshtastic.identity import (
    FIRMWARE_HEADER,
    NODE_NUM_HEADER,
    PUBKEY_HEADER,
    FeederIdentity,
    read_identity,
)
from test.meshtastic.fake_interface import PUBKEY_B64, FakeInterface


def test_27_shaped_interface_reads_every_field():
    identity = read_identity(FakeInterface(0x11223344))
    assert identity == FeederIdentity(
        node_num=0x11223344,
        pubkey=PUBKEY_B64,
        macaddr="a1:b2:c3:d4:e5:f6",
        firmware="2.7.11.abcdef0",
        region="EU_868",
        preset="LONG_FAST",
    )


def test_28_shaped_interface_without_mac_has_absent_mac():
    iface = FakeInterface(
        0x4396524C, macaddr_b64=None, firmware="2.8.2.deadbee", region=None
    )
    identity = read_identity(iface)
    assert identity.node_num == 0x4396524C
    assert identity.macaddr is None
    assert identity.region == "UNSET"
    assert "meshtastic_macaddr" not in identity.bot_version_fields()


def test_empty_or_all_zero_mac_is_absent():
    zero = base64.b64encode(bytes(6)).decode()
    assert read_identity(FakeInterface(macaddr_b64=zero)).macaddr is None
    assert read_identity(FakeInterface(macaddr_b64="")).macaddr is None


def test_missing_key_firmware_and_config_are_none_not_empty():
    iface = FakeInterface(
        pubkey_b64=None,
        macaddr_b64=None,
        firmware=None,
        lora_config_received=False,
    )
    identity = read_identity(iface)
    assert identity.node_num == 0x11223344
    assert identity.pubkey is None
    assert identity.macaddr is None
    assert identity.firmware is None
    assert identity.region is None
    assert identity.preset is None
    assert identity.headers() == {NODE_NUM_HEADER: str(0x11223344)}
    assert identity.bot_version_fields() == {"meshtastic_node_num": 0x11223344}


def test_empty_strings_from_the_library_become_absent():
    iface = FakeInterface(pubkey_b64="", firmware="")
    identity = read_identity(iface)
    assert identity.pubkey is None
    assert identity.firmware is None


def test_custom_modem_settings_report_no_preset():
    identity = read_identity(FakeInterface(use_preset=False))
    assert identity.region == "EU_868"
    assert identity.preset is None


def test_unknown_region_value_from_a_newer_firmware_is_reported_not_dropped():
    iface = FakeInterface()
    iface.localNode.localConfig.lora.region = 99
    assert read_identity(iface).region == "UNKNOWN_99"


def test_non_default_preset_name():
    iface = FakeInterface(preset=config_pb2.Config.LoRaConfig.MEDIUM_FAST)
    assert read_identity(iface).preset == "MEDIUM_FAST"


def test_bare_interface_reads_nothing_and_does_not_raise():
    class Bare:
        pass

    assert read_identity(Bare()) == FeederIdentity()


def test_security_config_section_is_never_read():
    iface = FakeInterface()
    iface.localNode.localConfig.security.private_key = b"\x07" * 32
    identity = read_identity(iface)
    flat = (
        repr(identity) + repr(identity.headers()) + repr(identity.bot_version_fields())
    )
    assert base64.b64encode(b"\x07" * 32).decode() not in flat
    assert PUBKEY_B64 in flat


def test_headers_carry_pubkey_node_num_and_firmware():
    headers = read_identity(FakeInterface(0x11223344)).headers()
    assert headers == {
        PUBKEY_HEADER: PUBKEY_B64,
        NODE_NUM_HEADER: str(0x11223344),
        FIRMWARE_HEADER: "2.7.11.abcdef0",
    }


def test_header_values_are_ascii_safe():
    headers = FeederIdentity(firmware="2.8.0☃\r\nX-Evil: 1").headers()
    assert "\r" not in headers[FIRMWARE_HEADER]
    assert "\n" not in headers[FIRMWARE_HEADER]
    assert headers[FIRMWARE_HEADER].isascii()


def test_bot_version_fields_full():
    fields = read_identity(FakeInterface(0x11223344)).bot_version_fields()
    assert fields == {
        "meshtastic_public_key": PUBKEY_B64,
        "meshtastic_node_num": 0x11223344,
        "meshtastic_firmware_version": "2.7.11.abcdef0",
        "meshtastic_macaddr": "a1:b2:c3:d4:e5:f6",
        "meshtastic_region": "EU_868",
        "meshtastic_modem_preset": "LONG_FAST",
    }
