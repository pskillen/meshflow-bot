# MeshCore packet and event fields (Phase 0.4 — capture-verified)

This document describes the **JSON shapes actually written by `meshflow-bot`** during the Phase 0.4 capture campaign (see [README.md](./README.md)). It complements upstream MeshCore / `meshcore_py` documentation: anything listed here was checked against at least one file under `docs/meshcore_packets/`.

**Envelope (every dumped file):**

| Field | Type | Description |
|-------|------|-------------|
| `protocol` | string | Always `meshcore`. |
| `event_type` | string | Subfolder name / `meshcore` event discriminator (e.g. `rx_log_data`, `channel_message`). |
| `payload` | object | Event payload; may be empty `{}`. |
| `attributes` | object | Parallel metadata from the `meshcore` event; often repeats a subset of `payload` for indexing. |

Nested keys use **snake_case** in dumps. Integer times such as `recv_time` / `sender_timestamp` are **Unix seconds** in the samples reviewed.

---

## `advertisement`

| Field path | Type | Notes |
|------------|------|--------|
| `payload.public_key` | string (hex) | 64 hex chars = 32-byte Ed25519 public key (lowercase in samples). |
| `attributes.public_key` | string | Same as payload in samples. |

---

## `channel_message` (decoded group text; files may live under `channel_messages/`)

| Field path | Type | Notes |
|------------|------|--------|
| `payload.type` | string | `"CHAN"` in samples. |
| `payload.channel_idx` | integer | Zero-based channel index. |
| `payload.path_hash_mode` | integer | Routing / hash mode flag on wire. |
| `payload.path_len` | integer | Count of path hops represented in frame. |
| `payload.txt_type` | integer | Text subtype (0 in samples). |
| `payload.sender_timestamp` | integer | Sender clock (Unix s). |
| `payload.text` | string | UTF-8 channel message body. |
| `attributes.channel_idx` | integer | Duplicate of `payload.channel_idx`. |
| `attributes.txt_type` | integer | Duplicate of `payload.txt_type`. |

**Capture note:** Channel frames may not carry a full sender pubkey; the bot uses a synthetic `from_id` for dispatch. See [`src/meshcore/translation.py`](../../src/meshcore/translation.py).

---

## `contact_message` (decoded DM / private text)

| Field path | Type | Notes |
|------------|------|--------|
| `payload.type` | string | `"PRIV"` in samples. |
| `payload.pubkey_prefix` | string (hex) | **12 hex chars** (6-byte prefix); used as partial sender identity. |
| `payload.path_hash_mode` | integer | |
| `payload.path_len` | integer | |
| `payload.txt_type` | integer | |
| `payload.sender_timestamp` | integer | |
| `payload.text` | string | Message body. |
| `attributes.pubkey_prefix` | string | Same prefix. |
| `attributes.txt_type` | integer | |

---

## `control_data`

| Field path | Type | Notes |
|------------|------|--------|
| `payload.SNR` | number | dB-like SNR as reported by stack. |
| `payload.RSSI` | integer | dBm. |
| `payload.path_len` | integer | |
| `payload.payload_type` | integer | Opaque type code (e.g. `146` in one sample). |
| `payload.payload` | string (hex) | Opaque body. |
| `attributes.payload_type` | integer | |

---

## `discover_response`

| Field path | Type | Notes |
|------------|------|--------|
| `payload.SNR` | number | |
| `payload.RSSI` | integer | |
| `payload.path_len` | integer | |
| `payload.node_type` | integer | Small integer enum (e.g. `2`). |
| `payload.SNR_in` | number | Inbound SNR where present. |
| `payload.tag` | string (hex) | Short tag (8 hex chars in samples). |
| `payload.pubkey` | string (hex) | Full 32-byte public key (64 hex). |
| `attributes.node_type` | integer | |
| `attributes.tag` | string | |
| `attributes.pubkey` | string | |

---

## `messages_waiting`

| Field path | Type | Notes |
|------------|------|--------|
| `payload` | object | Empty `{}` in committed samples. |
| `attributes` | object | Empty `{}` in committed samples. |

Semantics: push notification that the companion has traffic pending; no decoded text in these dumps.

---

## `path_update`

| Field path | Type | Notes |
|------------|------|--------|
| `payload.public_key` | string (hex) | Full 64-hex pubkey. |
| `attributes.public_key` | string | Same. |

---

## `rx_log_data` (raw RX / decoded packet log)

Common fields across samples:

| Field path | Type | Notes |
|------------|------|--------|
| `payload.raw_hex` | string | Full received frame as hex. |
| `payload.recv_time` | integer | RX time (Unix s). |
| `payload.snr` | number | |
| `payload.rssi` | integer | |
| `payload.payload` | string (hex) | Frame sans outer framing as emitted by decoder (see samples). |
| `payload.payload_length` | integer | Byte length. |
| `payload.header` | integer | Header byte / flags (varies by packet). |
| `payload.route_type` | integer | Numeric route discriminator. |
| `payload.route_typename` | string | e.g. `FLOOD`, `TC_FLOOD`, `DIRECT`. |
| `payload.payload_type` | integer | Numeric payload type. |
| `payload.payload_typename` | string | e.g. `TEXT_MSG`, `ADVERT`, `PATH`, `REQ`, `CONTROL`. |
| `payload.payload_ver` | integer | |
| `payload.path_len` | integer | |
| `payload.path_hash_size` | integer | Bytes per path hash segment. |
| `payload.path` | string (hex) | Concatenated path hash bytes (may be empty). |
| `payload.pkt_payload` | string (hex) | Inner payload hex. |
| `payload.pkt_hash` | integer | 32-bit-ish hash identifier on wire (signed 32-bit in JSON number). |
| `attributes.recv_time` | integer | |
| `attributes.route_type` | integer | |
| `attributes.payload_type` | integer | |
| `attributes.path_len` | integer | |
| `attributes.path` | string | |

**Optional** (present when decoder expands the frame — seen on `ADVERT` and some `REQ`):

| Field path | Type | Notes |
|------------|------|--------|
| `payload.transport_code` | string (hex) | Seen on `REQ` / `PATH` / `ADVERT` samples. |
| `payload.adv_name` | string | Human-readable name from advert. |
| `payload.adv_key` | string (hex) | Advertised key material (prefix / key field). |
| `payload.adv_timestamp` | integer | |
| `payload.signature` | string (hex) | Long Ed25519 signature (128 hex). |
| `payload.adv_flags` | integer | |
| `payload.adv_type` | integer | |
| `payload.adv_lat` | number | Observed `0.0` when position absent. |
| `payload.adv_lon` | number | Observed `0.0` when position absent. |

---

## `trace_data`

| Field path | Type | Notes |
|------------|------|--------|
| `payload.tag` | integer | Request / trace correlation value (32-bit style). |
| `payload.auth` | integer | |
| `payload.flags` | integer | |
| `payload.path_len` | integer | Number of hops described. |
| `payload.path` | array | List of hop objects. |
| `payload.path[].hash` | string (hex) | Present on some hops (1-byte `f3` style in sample). |
| `payload.path[].snr` | number | SNR for hop. |
| `attributes.tag` | integer | Same as `payload.tag`. |
| `attributes.auth_code` | integer | Mirrors `payload.auth` in sample. |

---

## Types not present in this capture tree

The following `meshcore` paths are handled in code but **did not produce JSON files** in this bundle (search the tree for `event_type` if that changes):

- `battery` / battery telemetry pushes  
- `self_info` / `device_info` as standalone dump files  
- Dedicated `ack` event dumps  

Absence here does **not** mean the mesh never sends them — only that this listener did not persist files under `docs/meshcore_packets/` for those types during this run. Use that fact when scoping Phase 0.5 ADRs ([meshflow-api#276](https://github.com/pskillen/meshflow-api/issues/276)).

---

## Mapping hint for future API ingest

For ingestion design, treat **`rx_log_data`** as the authoritative per-packet record (`payload_typename`, route, hashes, optional advert decode). Treat **`channel_message`** / **`contact_message`** as already-decoded text views. Keep **`protocol": "meshcore"`** on every JSON line for mixed-protocol tooling.
