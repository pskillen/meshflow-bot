#!/usr/bin/env python3
"""Print a radio's identity snapshot as one JSON line.

    python tools/meshtastic_capture/identity.py <serial-port-or-host>

Public data only: node number, public key, the number a 2.8 firmware derives
from that key (crc32), whether they match, the MAC and the firmware version.
The result is safe to commit (see ``docs/meshtastic_packets/2.8/identity/``).
Never dump the security config: it holds the private key.
"""

from __future__ import annotations

import base64
import json
import sys
import zlib


def main(argv: list[str]) -> int:
    import meshtastic.serial_interface as s
    import meshtastic.tcp_interface as t

    if len(argv) < 2:
        print(__doc__)
        return 2
    a = argv[1]
    i = s.SerialInterface(a) if a.startswith("/dev") else t.TCPInterface(a)
    n = i.myInfo.my_node_num
    pk = bytes(i.localNode.localConfig.security.public_key)
    c = zlib.crc32(pk) & 0xFFFFFFFF
    u = i.nodesByNum[n]["user"]
    print(
        json.dumps(
            {
                "id": f"!{n:08x}",
                "num": n,
                "pubkey_b64": base64.b64encode(pk).decode(),
                "pubkey_len": len(pk),
                "crc32_id": f"!{c:08x}",
                "match": c == n,
                "macaddr": u.get("macaddr"),
                "fw": getattr(i.metadata, "firmware_version", None),
            }
        )
    )
    i.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
