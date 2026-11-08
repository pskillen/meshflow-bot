# Meshtastic

[Meshtastic](https://meshtastic.org) is an open LoRa mesh firmware ecosystem. Meshflow Bot speaks to a node over **TCP** using the official [`meshtastic`](https://pypi.org/project/meshtastic/) Python library. The adapter lives under [`src/meshtastic/`](../src/meshtastic/).

## Connection

| Variable | Description |
|----------|-------------|
| `RADIO_PROTOCOL` | Use `meshtastic` (default) or omit (defaults to Meshtastic). |
| `MESHTASTIC_IP` | Hostname or IP of the node’s TCP API (required for Meshtastic mode). |

The concrete radio implementation is `MeshtasticRadio` in [`src/meshtastic/radio.py`](../src/meshtastic/radio.py) (auto-reconnect TCP, pubsub, packet translation).

## Meshflow API upload

When `STORAGE_API_ROOT` is set and `RADIO_PROTOCOL=meshtastic`:

- **v3 (default):** `POST /api/v3/packets/{my_nodenum}/ingest/` for raw packets; node upsert uses strict `meshtastic_*` field names.
- **v2:** `POST /api/packets/{my_nodenum}/ingest/` (legacy URL prefix; server accepts legacy nested field aliases on node upsert).
- **v1:** `POST /api/raw-packet/`.

| Variable | Description |
|----------|-------------|
| `STORAGE_API_ROOT` | Base URL of meshflow-api |
| `STORAGE_API_TOKEN` | Bearer / API token |
| `STORAGE_API_VERSION` | `1`, `2`, or `3` (default `3` for new installs; use `2` only with older API builds) |
| `STORAGE_API_2_*` | Optional second destination |

Failed uploads can be retained under `data/failed_packets/` when configured.

## Feeder identity

In Meshtastic 2.8 a node's number becomes `crc32(public key)`, so a feeder's number can change when its firmware is upgraded (or when a key is minted after the region is set). The API identifies feeders by API key and uses what the bot reports here to notice and handle that change. The bot only **reports**; it is safe against current APIs, which ignore the extra headers and fields. Works unchanged on 2.7 radios (fields the radio doesn't have are simply left out, never sent empty).

What is read from the connected radio ([`src/meshtastic/identity.py`](../src/meshtastic/identity.py)):

| Item | Source | Notes |
|------|--------|-------|
| Public key | local node's NodeDB `user.publicKey` | base64, as the library reports it |
| MAC (OTA `macaddr`) | local node's NodeDB `user.macaddr` | sent as `aa:bb:cc:dd:ee:ff`; absent if the firmware doesn't report one |
| Node number | `myInfo.my_node_num` | |
| Firmware version | device metadata (`interface.metadata.firmware_version`) | |
| LoRa region, modem preset | `localConfig.lora` | e.g. `EU_868`, `LONG_FAST`; region `UNSET` if not configured; no preset when custom modem settings are in use |

The private key and the `security` config section are never read or sent.

Reported to the API on Meshtastic calls (not MeshCore):

- Headers on every request: `X-Meshtastic-Feeder-Pubkey`, `X-Meshtastic-Feeder-Node-Num`, `X-Meshtastic-Feeder-Firmware`.
- The bot-version report (`PUT …/bot-version/`) also carries `meshtastic_public_key`, `meshtastic_node_num`, `meshtastic_firmware_version`, `meshtastic_macaddr`, `meshtastic_region` and `meshtastic_modem_preset`. It is sent on connect and again whenever the reported identity changes (for instance once the region is set). A connection error, timeout or HTTP 5xx on this report, or on a node upload (including the connect-time NodeDB sync), is retried in the background (3 attempts in all, about a minute); 403/409 are never retried and use the back-off below.
- Node uploads (`POST …/nodes/`) carry the NodeDB entry's `lastHeard` as `last_heard` (ISO 8601 UTC), so the API can keep a newer on-air name over a stale NodeDB one. It is omitted when the radio reports none or 0. The API needs meshflow-api 2.2.1 or later for this field.

Change detection: on local `node.updated` events and every 60 seconds the bot re-reads the identity. If the node number changed it logs a WARNING, refreshes what it reports, re-sends the bot-version report and reconnects the WebSocket so it subscribes under the new number. A reconnect to a radio that now has a different number is handled the same way. (The Meshtastic library only learns a new number from a fresh `my_info`, so a number changed in the radio mid-session is picked up when the library next receives one.)

If the API answers an upload with **403 or 409**, the bot logs an ERROR naming the node number it reported and pointing at the 2.8 identity change, then pauses uploads with exponential backoff (30 s, doubling to 15 min) instead of retrying every packet. The first success resets the backoff. Check the feeder's API key and linked node in Meshflow; for the upgrade steps see the 2.8 upgrade runbook in the meshflow-api packet-ingestion docs.

## WebSocket commands

With `MESHFLOW_WS_URL` + token (or derived from `STORAGE_API_*`), the bot starts `MeshflowWSClient` for remote actions such as **traceroute** after the radio connects.

## Optional behaviour

| Variable | Description |
|----------|-------------|
| `IGNORE_PORTNUMS` | Comma-separated portnums to skip when uploading (upper-case, e.g. `ROUTING_APP`). |
| `DUMP_PACKETS_PORTNUMS` | Comma-separated Meshtastic `portnum` names (or `*`) to dump received packets under `<DATA_DIR>/packets/<PORTNUM>/`. Each file is `{packet, raw_b64, meta}`: `packet` is the library dict (bytes as base64), `raw_b64` is base64 of `MeshPacket.SerializeToString()` (keeps unknown fields such as the 2.8 signing fields, so it can be re-parsed with a newer lib), `meta` is `feeder_num`, `feeder_fw` (null if unavailable), `lib_version`, `captured_at`. See [`src/persistence/packet_dump.py`](../src/persistence/packet_dump.py). |
| `DUMP_NODEDB` | `true` / `false` (default `false`). On connect, write the radio's NodeDB (`interface.nodes`, bytes as base64) to `<DATA_DIR>/packets/_nodedb/<ts>.json`. Public keys only; config/security (private key) is never dumped. |
| `REPLAYED_PACKETS` | `drop` (default), `flag` or `pass`: what to do with the Meshtastic 2.8 connect-time replay. See [Connect-time replay](#connect-time-replay-28). |
| `SELF_TELEMETRY_UPLOAD_INTERVAL_SECONDS` | Seconds between uploads of the feeder's own telemetry (default `900`; `0` disables it entirely). See [Self telemetry](#self-telemetry). |
| `ADMIN_NODES` | Comma-separated `!hex8` node ids allowed to run admin commands. |
| `DATA_DIR` | Data root (default `data/`). |

## Connect-time replay (2.8)

After `config_complete_id`, a Meshtastic 2.8 radio sends the client one synthetic POSITION_APP, TELEMETRY_APP (device, environment) and NODE_STATUS_APP packet per NodeDB node, built from stored history: `rx_time` is the node's `last_heard`, `rx_snr` the stored SNR, and `rx_rssi` is **absent**. On an 83-node NodeDB that is about 80 packets within 1-4 minutes of every connect. Uploaded as live, they would show old readings as fresh receptions (wrong RSSI, wrong hops, a flood of duplicates on every reconnect).

The bot classifies each incoming packet before it becomes an `IncomingPacket` (`replayed` on the event): a packet is a replay only if all of these hold: `from` is not our own node number, it did not arrive via MQTT (`viaMqtt` true or `transportMechanism` naming MQTT), the dict has no `rxRssi` key, `transportMechanism` is `TRANSPORT_LORA` and `priority` is `BACKGROUND`. Across the four hardware captures this matches all 156 replayed packets and no live packet. Real LoRa receptions always carry a negative RSSI; our own packets never count. The check is one function (`_has_rx_rssi` in [`src/meshtastic/replay.py`](../src/meshtastic/replay.py)); with a 2.8 library, swap it for `has_rx_rssi`. 2.7 radios never produce the pattern, so nothing changes for them.

`REPLAYED_PACKETS`:

- `drop` (default): not uploaded, not counted as node activity. With `DUMP_PACKETS_PORTNUMS` on they are written to `<DATA_DIR>/replay/<PORTNUM>/` instead of `packets/`, so fixtures can label them.
- `flag`: uploaded with `"replayed": true` added to the ingest body (and dumped to `replay/`). Current APIs ignore the unknown key; the API twin is meshflow-api#488.
- `pass`: today's behaviour, replays are handled as live packets.

Each connect logs one INFO line once the burst goes quiet (30 s without a replayed packet), e.g. `replayed packets: 80 dropped in the first 95 s`. The running total is kept in the error counter `radio.replayed_packets` (visible in the bot's counter snapshot).

## Self telemetry

The connected radio reports its own telemetry (device metrics, local stats, power, environment, ... and any variant newer firmware adds) to the bot every few seconds. Other feeders used to capture these over the air, but Meshtastic 2.8 turns broadcast telemetry off by default, so the bot uploads them itself.

Uploading every report would flood the API (that is why self telemetry was once disabled), so the throttle is bot-side only:

- The bot keeps the **latest sample per telemetry variant**.
- Every `SELF_TELEMETRY_UPLOAD_INTERVAL_SECONDS` (default 900, i.e. 15 minutes) a scheduled job uploads the newest unsent sample of each variant through the normal packet-report path, so the API ingests it as telemetry. Variants with nothing new are skipped.
- `0` disables self-telemetry uploads completely.
- Packets sent without `rxTime` (the API requires it) get the host clock's time before upload. This applies to every Meshtastic packet.
- There is no server-side throttling: it would still cost a request per sample.

Code: [`src/meshtastic/self_telemetry.py`](../src/meshtastic/self_telemetry.py). MeshCore is unchanged.

## Sample packet JSON

Example Meshtastic-shaped packets for tests/docs live under [`docs/meshtastic_packets/`](meshtastic_packets/) (encrypted, nodeinfo, position, routing, telemetry, text).

## Packet fixtures

Real radio output from a 2.7 / 2.8 hardware session (scrubbed: every position rounded to 0.1 degrees) lives in
[`docs/meshtastic_packets/2.8/`](meshtastic_packets/2.8/README.md): four captures, each with a manifest, a labelled
`subset.json` that meshflow-api's tests read by key, identity snapshots for the crc32 node-number checks, and the list of
captures still pending. Every record is labelled `self`, `live` or `replay` (the 2.8 connect replay).

- [`tools/meshtastic_capture/`](../tools/meshtastic_capture/): `capture.py` (lossless serial/TCP capture) and
  `identity.py` (public identity snapshot). Never commit their raw output.
- [`tools/meshtastic_fixtures/`](../tools/meshtastic_fixtures/): `build_fixtures.py` (raw capture or a bot dump tree to a
  scrubbed capture directory), `check_fixtures.py` (verifies the committed tree) and `load.py` (stdlib-only loader).

```bash
python tools/meshtastic_fixtures/check_fixtures.py docs/meshtastic_packets/2.8
pytest test/fixtures -q
```

To add a capture, dump with `DUMP_PACKETS_PORTNUMS=*` and `DUMP_NODEDB=true`, then run `build_fixtures.py` on the
`DATA_DIR`; the README there has the steps.

## Running

```bash
source venv/bin/activate
export RADIO_PROTOCOL=meshtastic   # optional; this is the default
export MESHTASTIC_IP=192.168.1.50
export STORAGE_API_ROOT=https://api.example.com
export STORAGE_API_TOKEN=...
export STORAGE_API_VERSION=2
python -m src.main
```

Docker: use the `meshflow-bot-meshtastic` service in [`docker-compose.yaml`](../docker-compose.yaml).

## See also

- [MeshCore capture mode](MESHCORE.md) — second protocol, USB/BLE, no API upload in Phase 0.3.
