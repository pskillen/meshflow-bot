#!/usr/bin/env python3
"""Lossless capture of every packet a Meshtastic radio hands the client.

    python tools/meshtastic_capture/capture.py <serial-port-or-host> <out.jsonl> [seconds]

A port starting with ``/dev`` opens a serial interface, anything else a TCP
interface. Writes one JSON object per line to ``<out>.jsonl``::

    {"t_host": <float>, "raw_b64": <MeshPacket bytes>, "packet": <lib dict without "raw">}

plus ``<out>_nodedb.json`` (``interface.nodes``) and ``<out>_meta.json``
(``my_info``, ``metadata``, ``t_host``, ``lib``) at start.

**Never commit this output.** It holds other people's real positions and the
radio's ``deviceId``. Run ``tools/meshtastic_fixtures/build_fixtures.py`` on it
first and commit only what that writes. The bot itself can also produce the
input: run it with ``DUMP_PACKETS_PORTNUMS=*`` and ``DUMP_NODEDB=true``.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from importlib.metadata import PackageNotFoundError, version


def _lib_version() -> str:
    try:
        return version("meshtastic")
    except PackageNotFoundError:
        return "?"


def main(argv: list[str]) -> int:
    import meshtastic.serial_interface
    import meshtastic.tcp_interface
    from google.protobuf.json_format import MessageToDict
    from pubsub import pub

    if len(argv) < 3:
        print(__doc__)
        return 2
    target, out = argv[1], argv[2]
    secs = int(argv[3]) if len(argv) > 3 else 1800
    stem = out[:-6] if out.endswith(".jsonl") else out
    f = open(out, "a")
    lock = threading.Lock()
    count = {"n": 0}

    def enc(o):
        if isinstance(o, (bytes, bytearray)):
            return base64.b64encode(bytes(o)).decode()
        try:
            return MessageToDict(o)
        except Exception:
            return str(o)

    def on_rx(packet, interface):
        raw = packet.get("raw")
        rec = {
            "t_host": time.time(),
            "raw_b64": (
                base64.b64encode(raw.SerializeToString()).decode()
                if raw is not None
                else None
            ),
            "packet": {k: v for k, v in packet.items() if k != "raw"},
        }
        with lock:
            f.write(json.dumps(rec, default=enc) + "\n")
            f.flush()
            count["n"] += 1

    pub.subscribe(on_rx, "meshtastic.receive")
    iface = (
        meshtastic.serial_interface.SerialInterface(target)
        if target.startswith("/dev")
        else meshtastic.tcp_interface.TCPInterface(target)
    )
    time.sleep(2)
    with open(stem + "_meta.json", "w") as m:
        json.dump(
            {
                "my_info": MessageToDict(iface.myInfo),
                "metadata": MessageToDict(iface.metadata),
                "t_host": time.time(),
                "lib": _lib_version(),
            },
            m,
            default=enc,
            indent=1,
        )
    with open(stem + "_nodedb.json", "w") as n:
        json.dump(
            {str(k): v for k, v in iface.nodes.items()}, n, default=enc, indent=1
        )
    print(
        f"capturing on {target} for {secs}s -> {out}; nodedb {len(iface.nodes)} nodes",
        flush=True,
    )
    t0 = time.time()
    while time.time() - t0 < secs:
        time.sleep(30)
        print(f"{int(time.time() - t0)}s {count['n']} packets", flush=True)
    iface.close()
    print("done", count["n"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
