# Meshtastic 2.7 / 2.8 hardware-session packet fixtures

Scrubbed captures of real radio output from one afternoon on a desk, comparing a 2.7 feeder with the same radio on 2.8.
They exist so the bot (and, through `subset.json`, meshflow-api) can be tested against what a radio really hands the
client, instead of hand-written dicts. Part of the Meshtastic 2.8 epic (meshflow-api#437); this directory is ticket
FX-1 (meshflow-api#463).

Status: nine captures committed (four from the Xiao on 2026-11-08, five from a Heltec Wireless Paper on 2026-11-09);
three slots are still pending (see [Known gaps](#known-gaps-and-pending-slots)). No bot behaviour is changed by these
files; the tests in `test/fixtures/` only pin what the bot does today.

| What | Where |
|---|---|
| Index of captures and pending slots | [`captures.json`](captures.json) |
| Per capture: counts, feeder, scrub numbers | `captures/<id>/manifest.json` |
| Per capture: the records | `captures/<id>/capture.jsonl` (one JSON object per line) |
| Per capture: the radio's NodeDB at capture start | `captures/<id>/nodedb.json` |
| Labelled subset, one entry per interesting packet | [`subset.json`](subset.json) |
| Identity snapshots (public key, number, MAC) | `identity/` |
| Tools | `tools/meshtastic_capture/`, `tools/meshtastic_fixtures/` |
| Tests | `test/fixtures/` |

## How it was captured

- **When and where:** 2026-11-08 and 2026-11-09, indoors on a desk, local public Meshtastic mesh (EU_868). The radio hears about two
  packets a minute on 2.7 and far more on 2.8 (it also reports connect-replay and MQTT-downlinked packets).
  Start times in the tables are the first record's `t_host` in UTC; the hand-written session log used local time and
  is approximate, so trust the manifests.
- **Radio (2026-11-08):** one Seeed Xiao nRF52840 kit with a Wio-SX1262, over USB serial, role CLIENT, region EU_868, no GPS.
  It was a managed node (NIAV-1) updated, re-keyed and downgraded during the session.
- **Radio (2026-11-09, "PDYt"):** a Heltec Wireless Paper (ESP32-S3, `HELTEC_WIRELESS_PAPER`), over USB serial, role
  CLIENT, region EU_868, signature policy COMPATIBLE, `hop_limit` 7 (read from its own packets' `hopLimit`; the session
  notes did not record it), wifi on. Captured on 2.7.20, then on 2.8.2.d5f1619 after an update-path flash that kept the
  key. The Xiao (`!faec6f41`, 2.8.2) was the second node: the sender of the traceroute, the signed NodeInfo and the DMs.
  The PDYt captures came over serial with `tools/meshtastic_capture/capture.py`, **not** from a bot dump, so they have
  no `replay/` folder; the connect replay burst is still visible in them (see below) and is classified by the same rule.
- **Tool and lib:** `tools/meshtastic_capture/capture.py` (ported from the session's `fx1_capture.py`), which writes
  `{t_host, raw_b64, packet}` per packet: `raw_b64` is the `MeshPacket` bytes, `packet` the python library's dict.
  `x27` used meshtastic-python 2.7.11 from PyPI; the three 2.8 captures used python master at `0a18357`, which carries
  the 2.8 protos but still reports version 2.7.11. The library version was not recorded in the capture metadata (the
  tool now records it). The PDYt captures have the same gap: `p27` is from the 2.7.11 venv, the 2.8 ones from the
  `0a18357` venv, as far as the session's venv layout says. `xeddsaSigned` is in the signed record's dict because that
  lib carried the 2.8 protos; the bot's serializer (`_sanitise_raw_packet`) keeps unknown keys, so that record's upload
  body carries `xeddsaSigned: true` even on today's code, and `raw_b64` carries field 22 (the lib round-trips it as an
  unknown field; the builder's byte-for-byte assertion held).
- **Raw output is never committed.** The raw files hold other people's real positions (some `LOC_MANUAL` with full
  32-bit precision, i.e. homes) and the radio's hardware identifier. They stay with the session owner;
  `build_fixtures.py` turned them into what is committed here.

### The devices and captures

| Capture id (short) | Feeder | Firmware | What was going on |
|---|---|---|---|
| `2026-11-08-xiao-2.7.26` (`x27`) | `!1a83cf89` | 2.7.26.54e0d8d | 30 min on 2.7; 80-node NodeDB. `hop_limit` was still the factory 6 (the session log's 3 was set later, after this capture). No replay on 2.7 |
| `2026-11-08-xiao-2.8.2` (`x28`) | `!e0a76739` | 2.8.2.d5f1619 | Same radio and key after the 2.8.2 update (the number changed, see the verdict below). `hop_limit` 3, policy COMPATIBLE. Starts with the connect replay burst. 83-node NodeDB |
| `2026-11-08-xiao-2.8.2-hop4` (`x28h4`) | `!e0a76739` | 2.8.2.d5f1619 | 5 min with `hop_limit` 4: the burst repeats and its `hopStart` is now 4 |
| `2026-11-08-xiao-2.8.2-faec6f41` (`x28f`) | `!faec6f41` | 2.8.2.d5f1619 | Re-keyed, then 2.8 to 2.7 to 2.8 round trip. The NodeDB came back empty, so there is no replay burst and no clock (18 live packets lack `rxTime`) |
| `2026-11-09-pdyt-2.7.20` (`p27`) | `!433b82f0` | 2.7.20.6658ec2 | PDYt before the update: a 2.7 ESP32 feeder, 10 min, 200-node NodeDB. **All 13 non-self packets are `TRANSPORT_MULTICAST_UDP`** (no RSSI, no SNR): the radio heard the mesh over its wifi multicast, not LoRa. Two encrypted packets, one STORE_FORWARD. No sender with a crc32 number |
| `2026-11-09-pdyt-2.8.2-traceroute` (`p28t`) | `!8959691b` | 2.8.2.d5f1619 | PDYt right after the update: the Xiao's TRACEROUTE to PDYt, the ROUTING reply and a POSITION (2.8 x 2.8, unicast), plus a 32-packet replay burst |
| `2026-11-09-pdyt-2.8.2-signed` (`p28s`) | `!8959691b` | 2.8.2.d5f1619 | The Xiao on BALANCED, rebooted twice: one broadcast NODEINFO with **`xeddsaSigned: true`** (line 16; 2.8 feeder x 2.8 signer). Its unsigned unicast NodeInfo to PDYt is line 2 |
| `2026-11-09-pdyt-2.8.2-passive` (`p28`) | `!8959691b` | 2.8.2.d5f1619 | 60 min passive, bot off: 2.8 feeder x live 2.7 senders (the number is the MAC tail, e.g. `!46220165`) and 2.8 senders (`!23c3c49f`, `!16162250`, `!faec6f41`), and a 32-packet connect replay burst on a 61-node NodeDB. No `xeddsaSigned` (no signer heard) |
| `2026-11-09-pdyt-2.8.2-dm` (`p28d`) | `!8959691b` | 2.8.2.d5f1619 | The Xiao's text DM and `PAGING_APP` (port 38) DM to PDYt, both `pkiEncrypted`, plus a 46-packet replay burst |

Not committed: `postflash` (6 records: the first minutes after the flash, 4-node NodeDB) and `D1b` (16 records: DM retries
and unicast NodeInfo exchanges). They add no cell the five above lack (no new port, sender kind or flag); the facts that
matter from them are in the NodeDB section below. The raw D1_D2 capture became `p28t`, D4 `p28s`, passive60 `p28`, D1d
`p28d`.

The first text DM to `!8959691b` was NAKed `PKI_SEND_FAIL_PUBLIC_KEY` because the Xiao had no key for
the new number; it was delivered about an hour later, once the Xiao's NodeDB held PDYt's key. Only the delivered DMs are
in `p28d`.
## The connect replay burst and how it is labelled

After `config_complete_id` a 2.8 radio replays its NodeDB: one synthetic POSITION, TELEMETRY and (when stored)
NODE_STATUS packet per node, built from stored history. They look like receptions and are not. The two 2.8 captures
with a populated NodeDB each start with 78 of them (`x28`, `x28h4`).

Every record carries `kind`:

- `self`: `packet.from` equals the capture's feeder number (`my_info.myNodeNum`);
- `replay`: not self, **no `rxRssi` key, `transportMechanism == "TRANSPORT_LORA"` and `priority == "BACKGROUND"`**;
- `live`: everything else.

The rule fits all 156 Xiao burst records, all 121 PDYt burst records and no live record in any capture. The firmware marks real receptions as
`TRANSPORT_LORA` with an RSSI; MQTT-downlinked live packets are `TRANSPORT_MQTT` with no RSSI, which is why a missing
RSSI alone is not enough (the 13 live packets in `p27` have no RSSI because they are `TRANSPORT_MULTICAST_UDP`). The
checker asserts that `kind` equals the rule for every record, and that the bot's `src.meshtastic.replay.is_replayed`
agrees on every record. It does, on all nine captures.

The burst is also seen over serial on an ESP32: 32 records within 0.4 s of the first in `p28` (61-node NodeDB), 32 in
`p28t`, 11 in `p28s` and 46 in `p28d`, all `hopStart` 7 (PDYt's `hop_limit`), no `rxRssi`, `TRANSPORT_LORA`,
`BACKGROUND`. The replay ids are stable across the PDYt captures (`stable_ids_shared_with` in the manifests) and are not
shared with the Xiao's.

What the burst looks like in the data: 78 records within 0.1 s of the first record (the client receives the whole
replay at once); one per (node, port); `hopStart` follows the feeder's `hop_limit` (3 in `x28`, 4 in `x28h4`); the
packet ids are **stable across reconnects** (61 of the 78 replay ids in `x28` reappear in `x28h4`; those subset entries carry
`stable-replay-id`); many have `hopStart == hopLimit` (`fake-direct`: they look like zero-hop receptions) or no
`hopLimit` at all.

## Self telemetry

The client is sent the radio's own telemetry continuously. Cadence per capture (from the manifests, median gap of
`deviceMetrics` by `t_host`):

| Capture | `deviceMetrics` count | Median gap | `localStats` count |
|---|---|---|---|
| `x27` | 31 | 60 s | 2 |
| `x28` | 30 | 60 s | 2 |
| `x28h4` | 5 | 60 s | 0 |
| `x28f` | 60 | 60 s | 4 |
| `p27` | 11 | 60 s | 0 |
| `p28t` | 15 | 60 s | 1 |
| `p28s` | 7 | 60 s | 0 |
| `p28` | 61 | 60 s | 4 |
| `p28d` | 4 | 60 s | 1 |

The bot's throttle (bot#152, `SELF_TELEMETRY_UPLOAD_INTERVAL_SECONDS`, default 900 s) is what keeps this off the API:
`test_meshtastic_2_8_fixtures.py` asserts that no self telemetry record is uploaded immediately and that the throttle
keeps one sample.

## Scrub rule (decided, applied before commit)

The captures are of the live public mesh and both repos are public, so third parties' positions are rounded:

- **Every latitude and longitude is rounded to 0.1 degrees** (about 11 km by 6 km at this latitude), for every node
  including ours, in all four places they appear, so the copies agree:
  1. `packet.decoded.position.{latitudeI, longitudeI, latitude, longitude}` and its `raw` copy;
  2. `packet.decoded.payload` (the `Position` bytes), decoded, rounded and re-encoded;
  3. `raw_b64` (the `MeshPacket`), decoded, inner position rounded, re-encoded. The builder asserts that the library
     re-serialises the untouched message byte for byte and that only the two coordinate fields differ afterwards;
  4. the NodeDB's `position` in `nodedb.json`.
  `latitudeI_new = round(latitudeI, -6)` and `latitude_new = latitudeI_new / 1e7`. Zero stays zero (so 0,0 handling is
  still testable) and absent stays absent. Altitude, time, `precisionBits` and the location source are kept.
- **Kept:** node numbers, packet ids, public keys (2.8 numbers are the crc32 of the key, so scrubbing would break the
  identity checks), MACs (a 2.7 number is the last four bytes of the MAC anyway), names, telemetry, SNR/RSSI, hop
  fields. Encrypted packets are kept as they are.
- **Dropped:** the radio's hardware identifier from the metadata, and any text message not sent by our own test nodes
  (the builder dropped five from the PDYt captures: three in the passive one, two in the DM one; the one text kept is
  `fx1 D`, from the Xiao to PDYt, and a manifest's `own_nodes` lists the test nodes the checker allows). No config or security dump is ever an
  input, and the checker fails on any key that looks like key material, a config secret or that identifier.

The PDYt captures' `my_info` carries the radio's hardware identifier; the builder never copies it.
`check_fixtures.py` verifies the grid on every committed position and, when `meshtastic` is installed, that the payload
and `raw_b64` decode to the same rounded position as the dict.

## Inventory

| Capture (short) | Feeder | Firmware | hop_limit | Start (UTC, from `t_host`) | Duration | Records | live | replay | self | Senders (non-self) | Self deviceMetrics (median gap) | localStats |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `2026-11-08-xiao-2.7.26` (`x27`) | `!1a83cf89` | 2.7.26.54e0d8d | 6 | 2026-11-08T12:49:47Z | 1800 s | 63 | 30 | 0 | 33 | 25 | 31 (60 s) | 2 |
| `2026-11-08-xiao-2.8.2` (`x28`) | `!e0a76739` | 2.8.2.d5f1619 | 3 | 2026-11-08T13:32:03Z | 1776 s | 135 | 25 | 78 | 32 | 67 | 30 (60 s) | 2 |
| `2026-11-08-xiao-2.8.2-hop4` (`x28h4`) | `!e0a76739` | 2.8.2.d5f1619 | 4 | 2026-11-08T14:03:34Z | 288 s | 89 | 5 | 78 | 6 | 59 | 5 (60 s) | 0 |
| `2026-11-08-xiao-2.8.2-faec6f41` (`x28f`) | `!faec6f41` | 2.8.2.d5f1619 | 3 | 2026-11-08T14:24:12Z | 3540 s | 128 | 62 | 0 | 66 | 39 | 60 (60 s) | 4 |
| `2026-11-09-pdyt-2.7.20` (`p27`) | `!433b82f0` | 2.7.20.6658ec2 | 7 | 2026-11-09T16:32:05Z | 591 s | 24 | 13 | 0 | 11 | 13 | 11 (60 s) | 0 |
| `2026-11-09-pdyt-2.8.2-traceroute` (`p28t`) | `!8959691b` | 2.8.2.d5f1619 | 7 | 2026-11-09T17:47:16Z | 892 s | 67 | 19 | 32 | 16 | 39 | 15 (60 s) | 1 |
| `2026-11-09-pdyt-2.8.2-signed` (`p28s`) | `!8959691b` | 2.8.2.d5f1619 | 7 | 2026-11-09T18:08:09Z | 412 s | 26 | 8 | 11 | 7 | 16 | 7 (60 s) | 0 |
| `2026-11-09-pdyt-2.8.2-passive` (`p28`) | `!8959691b` | 2.8.2.d5f1619 | 7 | 2026-11-09T19:31:03Z | 3594 s | 156 | 59 | 32 | 65 | 52 | 61 (60 s) | 4 |
| `2026-11-09-pdyt-2.8.2-dm` (`p28d`) | `!8959691b` | 2.8.2.d5f1619 | 7 | 2026-11-09T20:44:39Z | 198 s | 63 | 12 | 46 | 5 | 43 | 4 (60 s) | 1 |

| Capture | Ports (records) | Sender id scheme: mac / crc32 / neither / no user | Replay burst |
|---|---|---|---|
| `x27` | ENCRYPTED 2, NODEINFO 7, POSITION 12, TELEMETRY 42 | 10 / 0 / 0 (0 with a zeroed MAC) / 15 | none |
| `x28` | NODEINFO 9, POSITION 44, STORE_FORWARD 2, TELEMETRY 80 | 6 / 1 / 51 (51 with a zeroed MAC) / 9 | 78 within 0.1 s, hopStart [3] |
| `x28h4` | NODEINFO 2, POSITION 41, ROUTING 1, TELEMETRY 45 | 2 / 0 / 45 (45 with a zeroed MAC) / 12 | 78 within 0.1 s, hopStart [4] |
| `x28f` | NODEINFO 15, POSITION 27, ROUTING 4, STORE_FORWARD 1, TELEMETRY 78, TRACEROUTE 3 | 13 / 0 / 0 (0 with a zeroed MAC) / 26 | none |
| `p27` | ENCRYPTED 2, NODEINFO 2, POSITION 5, STORE_FORWARD 1, TELEMETRY 14 | 11 / 0 / 0 (0 with a zeroed MAC) / 2 | none (2.7) |
| `p28t` | NODEINFO 9, POSITION 27, ROUTING 1, TELEMETRY 29, TRACEROUTE 1 | 8 / 1 / 7 (7 with a zeroed MAC) / 23 | 32 within 0.2 s, hopStart [7] |
| `p28s` | NODEINFO 6, POSITION 10, TELEMETRY 10 | 3 / 2 / 11 (11 with a zeroed MAC) / 0 | 11 within 0.0 s, hopStart [7] |
| `p28` | NODEINFO 24, POSITION 42, ROUTING 1, TELEMETRY 88, TRACEROUTE 1 | 21 / 3 / 15 (15 with a zeroed MAC) / 13 | 32 within 0.4 s, hopStart [7] |
| `p28d` | NODEINFO 5, PAGING 1, POSITION 35, ROUTING 1, TELEMETRY 20, TEXT 1 | 4 / 1 / 24 (24 with a zeroed MAC) / 14 | 46 within 0.3 s, hopStart [7] |

`mac`: the sender's number equals the last four bytes of its MAC (a 2.7 or earlier node). `crc32`: it equals the crc32
of its 32-byte public key (a 2.8 node). Both are read from the capture's NodeDB plus any NODEINFO in the capture;
`neither` means the sender has a user record with a public key or MAC that matches neither; `no user` means no record, or a record with neither a public key nor a MAC (names only). The
feeder itself is excluded from the counts.

The `x28` `crc32` sender is `!23c3c49f`, a wild 2.8 node. **Not every other identified sender is `mac`**: the 2.8
NodeDB reports a zeroed MAC for almost every node (see below), so most `x28` and `x28h4` senders show as `neither`
with a zeroed MAC, which is "unidentifiable from the NodeDB", not "not a MAC node". Only a NODEINFO packet in the
capture carries the real MAC.

## The 2.8 NodeDB facts

- In `x28` 79 of the 83 NodeDB entries have an all-zero `macaddr` (the others: the feeder, one node heard live, and two
  entries with no `macaddr` key). In `x28h4` it is 85 of 97. On 2.7 (`x27`) none of the 80 is zeroed. A client reading
  the 2.8 NodeDB cannot derive "this node's number is its MAC" any more.
- The lib dict gives `macaddr` base64 (`+n4ag8+J`) on both versions.
- PDYt (ESP32) behaves the same: in `p28` 41 of the 61 NodeDB entries have an all-zero `macaddr` (on 2.7, in `p27`, 1 of
  200). **The update reset PDYt's NodeDB from 200 nodes to 4** (session snapshot straight after the flash; it had
  refilled to 61 by the passive capture), key and identity intact, and **the local node's own `macaddr` was still filled**
  (`SMpDO4Lw`, in `identity/pdyt_2.8.json`), as on the Xiao.
- `x28f` has a one-node NodeDB (itself) after the 2.8 to 2.7 to 2.8 round trip: the device state version differs
  (24 on 2.7, 25 on 2.8) and the NodeDB is not carried across. Identity (key, number, owner, channels) was intact.

## The crc32 verdict

A 2.8 firmware derives the node number from the public key: `num = crc32(public_key)`. The identity snapshots
(`identity/niav_*.json` and `identity/pdyt_*.json`, produced by `tools/meshtastic_capture/identity.py`) show it, and `test_meshtastic_2_8_fixtures.py`
re-derives every one of them:

| Step | Snapshot | Number | Key | crc32 of key | Matches |
|---|---|---|---|---|---|
| 2.7.26, before | `niav_2.7.json` | `!1a83cf89` | key A | `!e0a76739` | no (expected on 2.7) |
| Update to 2.8.2 | `niav_2.8.json` | **`!e0a76739`** | key A (unchanged) | `!e0a76739` | yes, as predicted |
| Re-key | `niav_2.8_rekeyed.json` | **`!faec6f41`** | key B | `!faec6f41` | yes; predicted from the new key before the write (`identity/rekey_predicted.txt`) |
| Downgrade to 2.7.26 | `niav_2.7_after_downgrade.json` | `!faec6f41` | key B | `!faec6f41` | yes: a rollback keeps the new number |
| Re-upgrade to 2.8.2 | `niav_2.8_after_reupgrade.json` | `!faec6f41` | key B | `!faec6f41` | yes |
| ESP32 (PDYt) 2.7.20, before | `pdyt_2.7.json` | `!433b82f0` | key P | `!8959691b` | no (expected on 2.7); the number is the last four bytes of the MAC `SMpDO4Lw` |
| ESP32 (PDYt) update to 2.8.2 | `pdyt_2.8.json` | **`!8959691b`** | key P (unchanged) | `!8959691b` | yes, as predicted: the same move on a Heltec Wireless Paper (ESP32-S3), MAC unchanged |

So: updating moves the number from `!1a83cf89` to its crc32 `!e0a76739` (and PDYt's from `!433b82f0` to `!8959691b`, on ESP32 too); a key change gives a new number and a reboot
(the bot's identity-change path, meshflow-api#442); a downgrade keeps the number. The wild 2.8 sender `!23c3c49f` matches
too (`x28-L85`: crc32 of the key in its NODEINFO equals its number).

## What the bot does with each kind today

Asserted by `test/fixtures/test_meshtastic_2_8_fixtures.py` through `MeshflowBot._on_packet` with a fake radio:

- `live` with `decoded`: uploaded once; `live` without `decoded` (encrypted, `x27-L37`): never uploaded.
- `replay`: not uploaded with `REPLAYED_PACKETS=drop` (the default); with `flag` uploaded once with `"replayed": true`.
- `self` telemetry: not uploaded immediately; the self-telemetry throttle records it.
- `self` ROUTING (the feeder's own ACK, `x28h4-L1`, `x28f-L8`): **uploaded once, like any decoded non-telemetry packet**.
  That is current behaviour, recorded here rather than endorsed.
- The signed NODEINFO (`p28s-L16`), the `pkiEncrypted` text DM (`p28d-L55`) and the `PAGING_APP` DM (`p28d-L58`) are
  `live` with `decoded`: each is uploaded once like any other. The bot does not read `xeddsaSigned` or `pkiEncrypted`
  today, and these rows pin that; the planned signing shim will be the first code that does.
- Every record translates to an event and serialises to JSON with no `raw` key at any depth and a filled `rxTime`.

## The labelled subset

`subset.json` holds 55 packets chosen for the cells that matter: each entry is
`{key, capture, src_line, id, from, kind, port, variant, labels, feeder_num, t_host, record: {raw_b64, packet}}`.
`record` is exactly the scrubbed line in the capture (the checker asserts it). **The keys are a contract** with the api
repo's golden tests and the cross-repo contract test; do not rename them. The first 36 rows (the Xiao captures, shorts
`x27`, `x28`, `x28h4`, `x28f`) are frozen: their records and labels are byte-identical to the first version; the 19
PDYt rows (`p27`, `p28`, `p28s`, `p28t`, `p28d`) were added after. `src_line` is the 1-based line in
`capture.jsonl`; it is also the line in the raw file for every capture where the builder dropped nothing (not `p28`, which dropped three
third-party texts, nor `p28d`, which dropped two).

Labels: always `feeder:2.7|2.8`, `kind:<kind>`, `port:<PORT or ENCRYPTED>`, `sender-id:mac|crc32|unknown`, and
`variant:<telemetry variant>` for telemetry; plus, where true, `no-rx-time`, `from-id-null` (`fromId` present and null),
`hops-exhausted` (`hopLimit` absent with `hopStart` set), `fake-direct` (replay with `hopStart == hopLimit`),
`bitfield:<n>`, `channel:<n>` and `stable-replay-id` (a replay id seen in more than one capture), `signed` (`xeddsaSigned` true) and `pki-encrypted`
(`pkiEncrypted` true). `pki-encrypted` is applied to the PDYt rows only: the Xiao row `x28h4-L1` is pkiEncrypted too
and stays without it, so the frozen rows keep their labels. `transport:udp-multicast` (`transportMechanism` present and not
`TRANSPORT_LORA`) marks the five `p27` non-self rows: they came over wifi, not LoRa, have no RSSI/SNR and are not a LoRa 2.7
reference; it is likewise left off the frozen rows.
`sender-id:unknown` covers a sender with no user record and one whose only identity is a zeroed MAC.

| Key | Kind | Port / variant | From | Labels | Why |
|---|---|---|---|---|---|
| `x27-L1` | self | TELEMETRY_APP / deviceMetrics | `!1a83cf89` | `feeder:2.7` `kind:self` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:mac` | 2.7 self telemetry (cadence) |
| `x27-L27` | self | TELEMETRY_APP / localStats | `!1a83cf89` | `feeder:2.7` `kind:self` `port:TELEMETRY_APP` `variant:localStats` `sender-id:mac` | 2.7 self localStats |
| `x27-L5` | live | NODEINFO_APP | `!433b10bc` | `feeder:2.7` `kind:live` `port:NODEINFO_APP` `sender-id:mac` `bitfield:0` | 2.7 feeder, MAC-id sender |
| `x27-L7` | live | POSITION_APP | `!60476689` | `feeder:2.7` `kind:live` `port:POSITION_APP` `sender-id:mac` `bitfield:0` | 7/5 hops |
| `x27-L9` | live | TELEMETRY_APP / environmentMetrics | `!e27aee72` | `feeder:2.7` `kind:live` `port:TELEMETRY_APP` `variant:environmentMetrics` `sender-id:unknown` `from-id-null` `bitfield:0` | fromId null |
| `x27-L10` | live | TELEMETRY_APP / deviceMetrics | `!229a5f0a` | `feeder:2.7` `kind:live` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:unknown` `from-id-null` `bitfield:0` |  |
| `x27-L12` | live | POSITION_APP | `!698239c8` | `feeder:2.7` `kind:live` `port:POSITION_APP` `sender-id:unknown` `from-id-null` `hops-exhausted` `bitfield:0` | hopLimit absent (0): hops exhausted |
| `x27-L23` | live | NODEINFO_APP | `!a0cc75a0` | `feeder:2.7` `kind:live` `port:NODEINFO_APP` `sender-id:mac` `from-id-null` `hops-exhausted` `bitfield:2` | bitfield 2, 3/0 |
| `x27-L37` | live | ENCRYPTED | `!f90bb907` | `feeder:2.7` `kind:live` `port:ENCRYPTED` `sender-id:unknown` `from-id-null` `hops-exhausted` `channel:9` | channel 9, no decoded: bot never uploads |
| `x28-L1` | live | NODEINFO_APP | `!7d085abc` | `feeder:2.8` `kind:live` `port:NODEINFO_APP` `sender-id:mac` `hops-exhausted` `bitfield:0` | live 3/0 during the burst |
| `x28-L2` | replay | POSITION_APP | `!0324c4a1` | `feeder:2.8` `kind:replay` `port:POSITION_APP` `sender-id:unknown` `hops-exhausted` `stable-replay-id` | replay, hopLimit 0 |
| `x28-L4` | replay | POSITION_APP | `!0ec53f95` | `feeder:2.8` `kind:replay` `port:POSITION_APP` `sender-id:unknown` `fake-direct` `stable-replay-id` | replay with hopStart == hopLimit: fake direct |
| `x28-L5` | replay | POSITION_APP | `!29212d31` | `feeder:2.8` `kind:replay` `port:POSITION_APP` `sender-id:unknown` `stable-replay-id` | replay 3/1 |
| `x28-L41` | replay | TELEMETRY_APP / deviceMetrics | `!0324c4a1` | `feeder:2.8` `kind:replay` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:unknown` `hops-exhausted` `stable-replay-id` | replay, hopLimit 0 |
| `x28-L42` | replay | TELEMETRY_APP / deviceMetrics | `!0ec53f95` | `feeder:2.8` `kind:replay` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:unknown` `fake-direct` `stable-replay-id` | fake direct |
| `x28-L43` | replay | TELEMETRY_APP / deviceMetrics | `!1f8d7181` | `feeder:2.8` `kind:replay` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:unknown` `stable-replay-id` | replay 3/1 |
| `x28-L80` | self | TELEMETRY_APP / deviceMetrics | `!e0a76739` | `feeder:2.8` `kind:self` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:crc32` | 2.8 self telemetry (every ~60 s) |
| `x28-L104` | self | TELEMETRY_APP / localStats | `!e0a76739` | `feeder:2.8` `kind:self` `port:TELEMETRY_APP` `variant:localStats` `sender-id:crc32` |  |
| `x28-L81` | live | POSITION_APP | `!7bc13c91` | `feeder:2.8` `kind:live` `port:POSITION_APP` `sender-id:unknown` `from-id-null` `bitfield:1` | bitfield 1 |
| `x28-L83` | live | STORE_FORWARD_APP | `!a35ae558` | `feeder:2.8` `kind:live` `port:STORE_FORWARD_APP` `sender-id:unknown` `from-id-null` `bitfield:1` | GenericPacket on the api |
| `x28-L85` | live | NODEINFO_APP | `!23c3c49f` | `feeder:2.8` `kind:live` `port:NODEINFO_APP` `sender-id:crc32` `from-id-null` `hops-exhausted` `bitfield:0` | 2.8 sender (number = crc32 of key): 2.8 x 2.8 cell |
| `x28-L86` | live | POSITION_APP | `!f8185202` | `feeder:2.8` `kind:live` `port:POSITION_APP` `sender-id:unknown` `bitfield:0` | 6/5 |
| `x28-L95` | live | TELEMETRY_APP / deviceMetrics | `!2a83b265` | `feeder:2.8` `kind:live` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:unknown` `bitfield:0` |  |
| `x28h4-L1` | self | ROUTING_APP | `!e0a76739` | `feeder:2.8` `kind:self` `port:ROUTING_APP` `sender-id:crc32` | self ACK, pkiEncrypted |
| `x28h4-L2` | live | TELEMETRY_APP / environmentMetrics | `!229a5f0a` | `feeder:2.8` `kind:live` `port:TELEMETRY_APP` `variant:environmentMetrics` `sender-id:unknown` `bitfield:0` |  |
| `x28h4-L4` | replay | POSITION_APP | `!0ec53f95` | `feeder:2.8` `kind:replay` `port:POSITION_APP` `sender-id:unknown` `fake-direct` `stable-replay-id` | same id as x28-L4, hops 4/4: stable replay id across reconnects |
| `x28f-L1` | self | TELEMETRY_APP / deviceMetrics | `!faec6f41` | `feeder:2.8` `kind:self` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:crc32` `no-rx-time` | no rxTime (no clock) |
| `x28f-L2` | self | TELEMETRY_APP / localStats | `!faec6f41` | `feeder:2.8` `kind:self` `port:TELEMETRY_APP` `variant:localStats` `sender-id:crc32` `no-rx-time` | no rxTime |
| `x28f-L35` | self | TELEMETRY_APP / deviceMetrics | `!faec6f41` | `feeder:2.8` `kind:self` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:crc32` | with rxTime |
| `x28f-L4` | live | POSITION_APP | `!69854e34` | `feeder:2.8` `kind:live` `port:POSITION_APP` `sender-id:unknown` `no-rx-time` `from-id-null` `bitfield:0` | no rxTime, precisionBits 13 |
| `x28f-L7` | live | TRACEROUTE_APP | `!43596b18` | `feeder:2.8` `kind:live` `port:TRACEROUTE_APP` `sender-id:mac` `no-rx-time` `from-id-null` `bitfield:2` | to the feeder, bitfield 2 (PDYb) |
| `x28f-L8` | self | ROUTING_APP | `!faec6f41` | `feeder:2.8` `kind:self` `port:ROUTING_APP` `sender-id:crc32` `no-rx-time` | self ACK |
| `x28f-L9` | live | ROUTING_APP | `!43596b18` | `feeder:2.8` `kind:live` `port:ROUTING_APP` `sender-id:mac` `no-rx-time` `from-id-null` `bitfield:0` | no hop fields |
| `x28f-L12` | live | NODEINFO_APP | `!43596b18` | `feeder:2.8` `kind:live` `port:NODEINFO_APP` `sender-id:mac` `no-rx-time` `from-id-null` `bitfield:0` `channel:1` | channel 1 |
| `x28f-L25` | live | STORE_FORWARD_APP | `!a35ae558` | `feeder:2.8` `kind:live` `port:STORE_FORWARD_APP` `sender-id:unknown` `no-rx-time` `from-id-null` `bitfield:1` | router heartbeat |
| `x28f-L42` | live | TELEMETRY_APP / environmentMetrics | `!8ec343c3` | `feeder:2.8` `kind:live` `port:TELEMETRY_APP` `variant:environmentMetrics` `sender-id:unknown` `from-id-null` `bitfield:0` |  |
| `p27-L1` | self | TELEMETRY_APP / deviceMetrics | `!433b82f0` | `feeder:2.7` `kind:self` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:mac` | PDYt (ESP32) 2.7 self telemetry |
| `p27-L4` | live | POSITION_APP | `!f101391a` | `feeder:2.7` `kind:live` `port:POSITION_APP` `sender-id:mac` `bitfield:0` `transport:udp-multicast` | 2.7 feeder (PDYt) x 2.7 sender, 7/3; wifi (UDP multicast), not LoRa: no RSSI/SNR |
| `p27-L5` | live | STORE_FORWARD_APP | `!a35ae558` | `feeder:2.7` `kind:live` `port:STORE_FORWARD_APP` `sender-id:mac` `bitfield:1` `transport:udp-multicast` | 2.7 feeder, router heartbeat; wifi (UDP multicast), not LoRa: no RSSI/SNR |
| `p27-L7` | live | NODEINFO_APP | `!433b10bc` | `feeder:2.7` `kind:live` `port:NODEINFO_APP` `sender-id:mac` `bitfield:0` `transport:udp-multicast` | 2.7 feeder (PDYt), MAC-id sender; wifi (UDP multicast), not LoRa: no RSSI/SNR |
| `p27-L12` | live | TELEMETRY_APP / deviceMetrics | `!2b6a77f6` | `feeder:2.7` `kind:live` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:mac` `bitfield:1` `transport:udp-multicast` | 2.7 feeder, 6/4; wifi (UDP multicast), not LoRa: no RSSI/SNR |
| `p27-L19` | live | ENCRYPTED | `!43596b18` | `feeder:2.7` `kind:live` `port:ENCRYPTED` `sender-id:unknown` `from-id-null` `channel:68` `transport:udp-multicast` | channel 68, no decoded: bot never uploads; wifi (UDP multicast), not LoRa: no RSSI/SNR |
| `p28-L1` | self | TELEMETRY_APP / deviceMetrics | `!8959691b` | `feeder:2.8` `kind:self` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:crc32` | PDYt (ESP32) 2.8 self telemetry |
| `p28-L8` | live | NODEINFO_APP | `!46220165` | `feeder:2.8` `kind:live` `port:NODEINFO_APP` `sender-id:mac` `bitfield:0` | 2.8 feeder x 2.7 sender (MAC-id) |
| `p28-L9` | live | TELEMETRY_APP / deviceMetrics | `!46220165` | `feeder:2.8` `kind:live` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:mac` `bitfield:0` | 2.8 feeder x 2.7 sender |
| `p28-L10` | live | POSITION_APP | `!46220165` | `feeder:2.8` `kind:live` `port:POSITION_APP` `sender-id:mac` `bitfield:0` | 2.8 feeder x 2.7 sender |
| `p28-L38` | replay | POSITION_APP | `!46220165` | `feeder:2.8` `kind:replay` `port:POSITION_APP` `sender-id:mac` `stable-replay-id` | replay burst over serial on a 61-node NodeDB, 7/6 |
| `p28-L55` | replay | POSITION_APP | `!faec6f41` | `feeder:2.8` `kind:replay` `port:POSITION_APP` `sender-id:crc32` `fake-direct` `stable-replay-id` | replay of the Xiao's own node, hopStart == hopLimit: fake direct |
| `p28-L61` | replay | TELEMETRY_APP / deviceMetrics | `!46220165` | `feeder:2.8` `kind:replay` `port:TELEMETRY_APP` `variant:deviceMetrics` `sender-id:mac` `stable-replay-id` | replay burst telemetry, 7/6 |
| `p28s-L16` | live | NODEINFO_APP | `!faec6f41` | `feeder:2.8` `kind:live` `port:NODEINFO_APP` `sender-id:crc32` `bitfield:0` `signed` | xeddsaSigned true: the Xiao on BALANCED, 2.8 feeder x 2.8 signer |
| `p28s-L2` | live | NODEINFO_APP | `!faec6f41` | `feeder:2.8` `kind:live` `port:NODEINFO_APP` `sender-id:crc32` `bitfield:2` | 2.8 x 2.8, unsigned unicast NodeInfo to the feeder |
| `p28t-L41` | live | TRACEROUTE_APP | `!faec6f41` | `feeder:2.8` `kind:live` `port:TRACEROUTE_APP` `sender-id:crc32` `bitfield:2` | 2.8 x 2.8 traceroute from the Xiao to the feeder |
| `p28t-L49` | live | POSITION_APP | `!faec6f41` | `feeder:2.8` `kind:live` `port:POSITION_APP` `sender-id:crc32` `bitfield:2` | 2.8 x 2.8 position from the Xiao, unicast to the feeder |
| `p28d-L55` | live | TEXT_MESSAGE_APP | `!faec6f41` | `feeder:2.8` `kind:live` `port:TEXT_MESSAGE_APP` `sender-id:crc32` `bitfield:0` `pki-encrypted` | text DM between our nodes, pkiEncrypted |
| `p28d-L58` | live | PAGING_APP | `!faec6f41` | `feeder:2.8` `kind:live` `port:PAGING_APP` `sender-id:crc32` `bitfield:0` `pki-encrypted` | port 38 DM, pkiEncrypted |

## Known gaps and pending slots

Now covered (from the PDYt session): a signed packet (`p28s-L16`, slot `pdyt-2.8-signing`); a 2.8 feeder with a populated
NodeDB hearing live 2.7 senders and a replay burst (`p28`, slot `pdyt-2.8-x-2.7-sender`; read over serial, so there is no
bot `replay/` folder); a 2.7 and a 2.8 ESP32 feeder; TEXT_MESSAGE_APP (ours only) and PAGING_APP, both pkiEncrypted
(`p28d`, half of slot `new-ports`); the 2.7 to 2.8 identity move on ESP32.

Still pending:

- **2.7 feeder x 2.8 sender** (`pdyb-2.7-x-2.8-sender`). It needs a 2.7 feeder that is not prod's PDYb. The 2.7 baseline
  here is PDYt, and it heard no crc32 sender: its 13 non-self packets all arrived as `TRANSPORT_MULTICAST_UDP`, from
  2.7 (MAC-number) senders.
- **MESH_BEACON_APP and NODE_STATUS_APP** (the rest of `new-ports`): neither was heard.
- **Traffic Management timeline** (position dedup). Slot `tm-dedup`.
- **No LoRa-heard 2.7 feeder**: `p27` is the only 2.7 ESP32 capture and its packets are UDP multicast, so it has no RSSI,
  SNR or `TRANSPORT_LORA`; the Xiao's `x27` is the LoRa 2.7 reference.
- The capturing library's version was not recorded in the metadata (`lib` was `?`); the manifests say what the session
  notes say.
- The older six samples in `docs/meshtastic_packets/` (`*_packet.json`, pre-2.8) are unchanged.

`captures.json` lists each pending slot with a one-line purpose, and each captured entry's `slot` field names the slot it
filled; a pending entry has no directory and passes the check.

## Checking and rebuilding

```bash
python tools/meshtastic_fixtures/check_fixtures.py docs/meshtastic_packets/2.8   # one OK line per capture, exit 0
pytest test/fixtures -q
```

The raw captures are not in the repo. The committed directories were built with, for each capture,
`python tools/meshtastic_fixtures/build_fixtures.py <raw>.jsonl --capture-id <id> --short <short> --out captures/<id> ...`
and the feeder settings recorded in each manifest (`--hop-limit`, `--role`, `--signature-policy`, `--lib-note`,
`--notes`; read the values back out of the manifest). The build is deterministic. `python
tools/meshtastic_fixtures/build_fixtures.py --subset docs/meshtastic_packets/2.8` is a second pass, run after all
captures are built: it rebuilds `subset.json` from the committed captures, also rewrites the cross-capture
`stable_ids_shared_with` in the manifests, and fails, naming the row, if a
listed line no longer has the kind, port, variant or sender in the table above.

## Adding a capture

1. Run the bot against the radio with `DUMP_PACKETS_PORTNUMS=*` and `DUMP_NODEDB=true` (see
   [`docs/MESHTASTIC.md`](../../MESHTASTIC.md)); replays go under `<DATA_DIR>/replay/`, the NodeDB under
   `<DATA_DIR>/packets/_nodedb/`. Or use `tools/meshtastic_capture/capture.py` on a serial port or host.
2. Build the scrubbed directory (never commit the raw one). For a bot dump:
   `python tools/meshtastic_fixtures/build_fixtures.py <DATA_DIR> --capture-id <id> --short <short> --out docs/meshtastic_packets/2.8/captures/<id> --hop-limit N --role CLIENT --signature-policy BALANCED --hw-model <MODEL> --own-node '!xxxxxxxx'`
   (`--own-node` for each test node whose text messages may be kept; every other `TEXT_MESSAGE_APP` is dropped; the
   manifest records them as `own_nodes` and the checker allows exactly those). For an fx1 serial capture pass the `.jsonl`
   (with `_meta.json` and `_nodedb.json` beside it) instead of the directory; the manifest's `notes` is free text.
3. In `captures.json` add the capture as `captured` (its `id` is the directory name, with `short`, `path` and the `slot`
   it fills) and remove or narrow the pending slot.
4. Add subset rows to the `SUBSET` table in `build_fixtures.py` and rerun it with `--subset`.
5. `check_fixtures.py` and `pytest test/fixtures`.
