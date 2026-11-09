"""Tests for :mod:`src.meshtastic.wire_fields` (2.8 signing fields via lib 2.7)."""

import unittest
from unittest import mock

from meshtastic.protobuf import mesh_pb2

from src.meshtastic.wire_fields import (
    SigningFields,
    is_firmware_2_8_or_later,
    read_signing_fields,
)

SIG = bytes(range(64))
SIGNED = b"\xb0\x01\x01"  # field 22 varint 1
ACK_VALID = b"\xb8\x01\x01"  # field 23 varint 1
ACK_NO_KEY = b"\xb8\x01\x03"


def decoded_with_sig(sig: bytes = SIG) -> bytes:
    # Data: portnum (1) varint 1, xeddsa_signature (10) LEN
    data = b"\x08\x01" + b"\x52" + bytes([len(sig)]) + sig
    return b"\x22" + bytes([len(data)]) + data


def parse(raw: bytes):
    pkt = mesh_pb2.MeshPacket()
    pkt.ParseFromString(raw)
    return pkt


class TestReadSigningFields(unittest.TestCase):
    def test_all_three(self):
        pkt = parse(decoded_with_sig() + SIGNED + ACK_VALID)
        # unknown to lib 2.7: not visible as attributes, but kept on the wire
        self.assertFalse(hasattr(pkt, "xeddsa_signed"))
        got = read_signing_fields(pkt)
        self.assertEqual(got, SigningFields(True, SIG, 1))

    def test_each_alone(self):
        self.assertEqual(read_signing_fields(parse(SIGNED)), SigningFields(True))
        self.assertEqual(
            read_signing_fields(parse(ACK_NO_KEY)),
            SigningFields(None, None, 3),
        )
        self.assertEqual(
            read_signing_fields(parse(decoded_with_sig())),
            SigningFields(None, SIG, None),
        )

    def test_none_present(self):
        self.assertEqual(read_signing_fields(parse(b"\x08\x05")), SigningFields())

    def test_explicit_false(self):
        self.assertEqual(
            read_signing_fields(parse(b"\xb0\x01\x00")).xeddsa_signed, False
        )

    def test_walker_skips_large_tags_before_and_after(self):
        # field 200 varint (tag 0xC2 0x0C... computed), field 300 LEN, and a
        # fixed32 field 99
        def tag(field, wire):
            v = (field << 3) | wire
            out = bytearray()
            while v > 0x7F:
                out.append((v & 0x7F) | 0x80)
                v >>= 7
            out.append(v)
            return bytes(out)

        before = tag(200, 0) + b"\xac\x02" + tag(300, 2) + b"\x03abc"
        after = tag(99, 5) + b"\x01\x02\x03\x04" + tag(1000, 0) + b"\x7f"
        raw = before + SIGNED + decoded_with_sig() + ACK_VALID + after
        self.assertEqual(read_signing_fields(parse(raw)), SigningFields(True, SIG, 1))

    def test_truncated_bytes_give_empty(self):
        raw = decoded_with_sig() + SIGNED
        class Fake:
            def SerializeToString(self):
                return raw[:20]

        self.assertEqual(read_signing_fields(Fake()), SigningFields())

    def test_serialize_raises_gives_empty(self):
        fake = mock.Mock()
        fake.SerializeToString.side_effect = RuntimeError("boom")
        self.assertEqual(read_signing_fields(fake), SigningFields())

    def test_none_gives_empty(self):
        self.assertEqual(read_signing_fields(None), SigningFields())


class TestFirmware(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(is_firmware_2_8_or_later("2.8.2.d5f1619"))
        self.assertTrue(is_firmware_2_8_or_later("2.10.0"))
        self.assertTrue(is_firmware_2_8_or_later("3.0.0"))
        self.assertFalse(is_firmware_2_8_or_later("2.7.26.abc"))
        self.assertIsNone(is_firmware_2_8_or_later(None))
        self.assertIsNone(is_firmware_2_8_or_later("garbage"))
        self.assertIsNone(is_firmware_2_8_or_later(""))


if __name__ == "__main__":
    unittest.main()
