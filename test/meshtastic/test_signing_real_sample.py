"""The signing shim against the real signed capture (SG-1).

``p28s-L16`` is a NODEINFO_APP signed by a 2.8.2 signer, captured by a 2.8.2
feeder on PDYt (docs/meshtastic_packets/2.8/captures/2026-11-09-pdyt-2.8.2-signed).
``p28s-L2`` is an unsigned NODEINFO_APP from the same capture. The raw bytes are
parsed with the pinned library's protos, which lack the 2.8 signing fields.
"""

import base64
import copy
import unittest
from pathlib import Path

from meshtastic.protobuf import mesh_pb2

from src.meshtastic.serializers import MeshtasticPacketSerializer
from src.meshtastic.wire_fields import read_signing_fields
from tools.meshtastic_fixtures.load import lib_packet, load_subset

ROOT = Path(__file__).resolve().parents[2] / "docs" / "meshtastic_packets" / "2.8"
FW_2_8 = "2.8.2.d5f1619"


def _entry(key):
    return next(e for e in load_subset(ROOT) if e["key"] == key)


def _raw(entry):
    msg = mesh_pb2.MeshPacket()
    msg.ParseFromString(base64.b64decode(entry["record"]["raw_b64"]))
    return msg


def _packet(entry):
    """The lib dict for the entry with the real parsed protobuf as ``raw``."""
    packet = lib_packet(entry)
    packet["raw"] = _raw(entry)
    return packet


class TestRealSignedSample(unittest.TestCase):
    def setUp(self):
        self.signed = _entry("p28s-L16")
        self.unsigned = _entry("p28s-L2")

    def test_reader_sees_signature_in_real_bytes(self):
        fields = read_signing_fields(_raw(self.signed))
        self.assertTrue(fields.xeddsa_signed)
        self.assertEqual(len(fields.signature), 64)
        # The capture's dict is the expected value. The bytes carry no
        # ack_proof_status (MeshPacket 23): a NODEINFO broadcast has none to prove.
        self.assertIs(self.signed["record"]["packet"]["xeddsaSigned"], True)
        self.assertIsNone(fields.ack_proof_status)
        self.assertNotIn("ackProofStatus", self.signed["record"]["packet"])
        self.assertEqual(
            base64.b64encode(fields.signature).decode("ascii"),
            self.signed["record"]["packet"]["decoded"]["xeddsaSignature"],
        )

    def test_reader_sees_unsigned_in_real_bytes(self):
        fields = read_signing_fields(_raw(self.unsigned))
        self.assertFalse(fields.xeddsa_signed)
        self.assertFalse(fields.signature)

    def test_signed_record_serialises_signed_with_signature(self):
        packet = _packet(self.signed)
        # Strip the dict's own keys so the shim, not the "dict wins" exit, supplies them.
        packet.pop("xeddsaSigned", None)
        packet["decoded"].pop("xeddsaSignature", None)
        out = MeshtasticPacketSerializer(
            firmware_version=lambda: FW_2_8
        ).serialise_raw_packet(packet)
        self.assertIs(out["xeddsaSigned"], True)
        sig = read_signing_fields(_raw(self.signed)).signature
        self.assertEqual(
            out["decoded"]["xeddsaSignature"], base64.b64encode(sig).decode("ascii")
        )

    def test_signed_flag_survives_when_dict_lacks_it(self):
        """The wire walker alone recovers the flag (what lib 2.7.11 would give)."""
        packet = _packet(self.signed)
        packet.pop("xeddsaSigned", None)
        packet["decoded"].pop("xeddsaSignature", None)
        out = MeshtasticPacketSerializer().serialise_raw_packet(packet)
        self.assertIs(out["xeddsaSigned"], True)
        self.assertEqual(len(base64.b64decode(out["decoded"]["xeddsaSignature"])), 64)

    def test_unsigned_record_is_false_on_2_8_firmware(self):
        out = MeshtasticPacketSerializer(
            firmware_version=lambda: FW_2_8
        ).serialise_raw_packet(_packet(self.unsigned))
        self.assertIs(out["xeddsaSigned"], False)
        self.assertNotIn("xeddsaSignature", out["decoded"])

    def test_unsigned_record_is_absent_when_firmware_unknown(self):
        for fw in (lambda: None, None):
            out = MeshtasticPacketSerializer(firmware_version=fw).serialise_raw_packet(
                _packet(self.unsigned)
            )
            self.assertNotIn("xeddsaSigned", out)

    def test_subset_output_without_firmware_matches_the_dict(self):
        """AC4: no firmware, stand-in raw: the serializer adds nothing to any record."""
        for entry in load_subset(ROOT):
            before = copy.deepcopy(lib_packet(entry))
            out = MeshtasticPacketSerializer().serialise_raw_packet(lib_packet(entry))
            self.assertEqual(
                out.get("xeddsaSigned"), before.get("xeddsaSigned"), entry["key"]
            )
            self.assertNotIn("ackProofStatus", out, entry["key"])


if __name__ == "__main__":
    unittest.main()
