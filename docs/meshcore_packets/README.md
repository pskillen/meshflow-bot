# MeshCore Phase 0.4 — real-world capture bundle

This directory holds JSON captures from the Phase 0.4 campaign described in [meshflow-api#275](https://github.com/pskillen/meshflow-api/issues/275) (child of [meshflow-api#264](https://github.com/pskillen/meshflow-api/issues/264)). The bot wrote one file per `meshcore` event under `data/meshcore_packets/<event_type>/`; the same tree is vendored here for review and schema work.

Inner JSON uses `event_type` exactly as `meshcore` reports it (e.g. `channel_message`). One folder in this bundle uses a plural spelling (`channel_messages/`); treat the file’s `event_type` field as canonical.

## Campaign ops note


| Item                    | Detail                                                                                                                                                                                                             |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Duration**            | Approximately **6 days** of wall-clock capture (UTC filenames span **2026-05-06** through **2026-05-12**). Only the top 5-10 packets from each category have been expanded to files. Full dataset in .tar.gz file. |
| **Location / mesh**     | **South Scotland** — traffic is consistent with the Dumfries and Galloway / Scottish MeshCore footprint (e.g. channel telemetry text referencing Galloway). Exact GPS of the listener radio was not logged.        |
| **Feeder setup**        | `meshflow-bot` with `RADIO_PROTOCOL=meshcore`, Phase **0.3** capture-only path (`MESHCORE_DUMP_ENABLED=true`, no API upload). See [docs/MESHCORE.md](../MESHCORE.md).                                              |
| **Firmware / git hash** | **All packets captured May 2026 were using 1.15.0 firmware**                                                                                                                                                       |
| **Archive**             | `meshcore_packets_20260512.tar.gz` is a tarball of this tree at hand-off time.                                                                                                                                     |


## Inventory (this bundle)

Event-type subfolders (filename prefix `YYYYMMDD_HHMMSS_microseconds.json`):


| Subfolder           | JSON files (approx.) | Role                                                                    |
| ------------------- | -------------------- | ----------------------------------------------------------------------- |
| `advertisement`     | 8                    | Heard node adverts (decoded public key in dump).                        |
| `channel_messages`  | 2                    | Public channel text (`CHAN`).                                           |
| `contact_messages`  | 2                    | DM-style text (`PRIV`, 12-hex sender prefix).                           |
| `control_data`      | 8                    | Companion control frames (opaque payload hex + RF meta).                |
| `discover_response` | 6                    | Neighbour discovery replies (full pubkey, RSSI/SNR).                    |
| `messages_waiting`  | 4                    | Push hint — empty payload in samples.                                   |
| `path_update`       | 1                    | Routing table style update (full pubkey).                               |
| `rx_log_data`       | 10                   | Per-packet RX log with route/payload typing and optional advert decode. |
| `trace_data`        | 7                    | Path trace / SNR vector samples.                                        |


High-frequency events (`no_more_messages`, `command_ok`, etc.) are intentionally **not** dumped; see `[src/meshcore/radio.py](../../src/meshcore/radio.py)`.

## Representative samples (one path per visible shape)

Use these when you need a single file to cite per category:


| Category                         | Example path                                    |
| -------------------------------- | ----------------------------------------------- |
| Advert (event)                   | `advertisement/20260506_211140_430432.json`     |
| Channel text                     | `channel_messages/20260507_094921_075978.json`  |
| Contact / DM text                | `contact_messages/20260506_205758_541689.json`  |
| Control                          | `control_data/20260506_211530_400099.json`      |
| Discover response                | `discover_response/20260506_211530_400913.json` |
| Messages waiting                 | `messages_waiting/20260506_205758_540343.json`  |
| Path update                      | `path_update/20260506_205759_895381.json`       |
| RX log — text                    | `rx_log_data/20260506_205758_495287.json`       |
| RX log — advert (decoded fields) | `rx_log_data/20260506_211819_583174.json`       |
| RX log — PATH                    | `rx_log_data/20260506_211515_351329.json`       |
| RX log — REQ                     | `rx_log_data/20260506_211618_132418.json`       |
| RX log — CONTROL                 | `rx_log_data/20260506_211530_398290.json`       |
| Trace data                       | `trace_data/20260507_154102_445613.json`        |


## Field reference

See **[MESHCORE_PACKET_FIELDS.md](./MESHCORE_PACKET_FIELDS.md)** for tables derived from these files (not from upstream prose alone).

## Downstream

A copy or derivative of `MESHCORE_PACKET_FIELDS.md` is expected under `meshflow-api/docs/features/packet-ingestion/` for API/OpenAPI alignment; this bot repo copy stays the provenance anchor tied to the capture tree.