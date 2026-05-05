import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

dump_portnums = os.getenv("DUMP_PACKETS_PORTNUMS", None)
if dump_portnums:
    dump_portnums = dump_portnums.split(",")
    dump_portnums = [p.strip().upper() for p in dump_portnums]
    # if any portnums == *, dump all portnums
    if "*" in dump_portnums:
        dump_portnums = ["*"]

    logging.info(f"Will dump all packets for portnums to JSON: {dump_portnums}")
else:
    logging.info("Not dumping packets - set DUMP_PACKETS_PORTNUMS to comma separated list of portnums to dump")


def dump_packet(packet: dict):
    global dump_portnums
    if not dump_portnums or len(dump_portnums) == 0:
        return

    portnum = packet["decoded"]["portnum"] if "decoded" in packet else "unknown"
    portnum = str(portnum).upper()

    if dump_portnums[0] != "*" and portnum not in dump_portnums:
        return

    # Create directory for this portnum if it doesn't exist
    portnum_dir = Path("data") / "packets" / str(portnum)
    portnum_dir.mkdir(parents=True, exist_ok=True)

    # Create a timestamp for the filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}.json"

    # Dump the packet to a JSON file
    try:
        with open(portnum_dir / filename, "w") as f:
            json.dump(packet, f, indent=4, default=str)
    except Exception as e:
        logging.error(f"Error dumping packet to JSON: {e}")
