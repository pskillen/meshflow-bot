"""Read the Meshtastic 2.8 signing fields from a raw ``MeshPacket``.

The bot is pinned to ``meshtastic<2.8`` (library 2.7.x), whose protobuf classes
do not know these fields, so they never reach the packet dict. They survive in
the raw protobuf object as unknown fields; this module reads them from the
serialised bytes with a small wire-format walker. With a 2.8 library the dict
carries the keys itself and this shim steps aside (see ``serializers.py``).

Field numbers (firmware protobufs v2.8.2):

* ``MeshPacket.decoded`` 4 (LEN), ``xeddsa_signed`` 22 (varint),
  ``ack_proof_status`` 23 (varint)
* ``Data.xeddsa_signature`` 10 (LEN)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DECODED = 4
_XEDDSA_SIGNED = 22
_ACK_PROOF_STATUS = 23
_XEDDSA_SIGNATURE = 10

ACK_PROOF_NAMES = {
    0: "ACK_PROOF_ABSENT",
    1: "ACK_PROOF_VALID",
    2: "ACK_PROOF_INVALID",
    3: "ACK_PROOF_NO_KEY",
}


@dataclass
class SigningFields:
    xeddsa_signed: Optional[bool] = None
    signature: Optional[bytes] = None
    ack_proof_status: Optional[int] = None


class _Malformed(Exception):
    pass


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf) or shift > 63:
            raise _Malformed("bad varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def _walk(buf: bytes):
    """Yield ``(field_number, wire_type, value)``; value is an int for varint
    and fixed fields, bytes for LEN. Groups are rejected as malformed."""
    pos = 0
    while pos < len(buf):
        tag, pos = _varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            if pos + 8 > len(buf):
                raise _Malformed("short fixed64")
            value, pos = int.from_bytes(buf[pos : pos + 8], "little"), pos + 8
        elif wire == 2:
            length, pos = _varint(buf, pos)
            if pos + length > len(buf):
                raise _Malformed("short LEN field")
            value, pos = buf[pos : pos + length], pos + length
        elif wire == 5:
            if pos + 4 > len(buf):
                raise _Malformed("short fixed32")
            value, pos = int.from_bytes(buf[pos : pos + 4], "little"), pos + 4
        else:
            raise _Malformed(f"unsupported wire type {wire}")
        yield field, wire, value


def read_signing_fields(raw_proto: Any) -> SigningFields:
    """Signing fields from ``raw_proto.SerializeToString()``. Never raises:
    a None argument or malformed bytes give an empty result."""
    if raw_proto is None:
        return SigningFields()
    try:
        data = raw_proto.SerializeToString()
        out = SigningFields()
        for field, wire, value in _walk(data):
            if field == _XEDDSA_SIGNED and wire == 0:
                out.xeddsa_signed = bool(value)
            elif field == _ACK_PROOF_STATUS and wire == 0:
                out.ack_proof_status = int(value)
            elif field == _DECODED and wire == 2:
                for sub, sub_wire, sub_value in _walk(value):
                    if sub == _XEDDSA_SIGNATURE and sub_wire == 2:
                        out.signature = bytes(sub_value)
        return out
    except Exception as exc:  # noqa: BLE001 - must never stop an upload
        logger.debug("read_signing_fields: could not parse packet: %s", exc)
        return SigningFields()


def is_firmware_2_8_or_later(version: Optional[str]) -> Optional[bool]:
    """True for firmware ``major.minor`` >= 2.8, False below, None if the
    value cannot be parsed (for example ``None`` or ``"garbage"``)."""
    if not isinstance(version, str):
        return None
    match = re.match(r"^\s*v?(\d+)\.(\d+)", version)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2))) >= (2, 8)
