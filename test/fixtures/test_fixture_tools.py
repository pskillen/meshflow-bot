"""Unit tests for the fixture tools (scrub, replay rule, builder, checker) on tiny inline records."""

import base64
import json
import tempfile
import unittest
from pathlib import Path

from meshtastic.protobuf import mesh_pb2, portnums_pb2

from tools.meshtastic_fixtures import build_fixtures, check_fixtures, rules

FEEDER = 100
LAT, LON = 559874048, -36372480  # 55.99, -3.64 -> 56.0, -3.6


def _position_bytes(lat=LAT, lon=LON, altitude=53, **extra) -> bytes:
    pos = mesh_pb2.Position(
        latitude_i=lat, longitude_i=lon, altitude=altitude, time=1755077015, **extra
    )
    return pos.SerializeToString()


def _meshpacket_b64(payload: bytes, portnum=portnums_pb2.POSITION_APP) -> str:
    mp = mesh_pb2.MeshPacket()
    setattr(mp, "from", 7)
    mp.to = 0xFFFFFFFF
    mp.id = 1234
    mp.hop_limit = 3
    mp.decoded.portnum = portnum
    mp.decoded.payload = payload
    return base64.b64encode(mp.SerializeToString()).decode()


def _position_packet(sender=7, **over):
    payload = _position_bytes()
    packet = {
        "from": sender,
        "to": 4294967295,
        "id": 1234,
        "rxTime": 1755078058,
        "rxSnr": 6.25,
        "hopStart": 3,
        "priority": "BACKGROUND",
        "transportMechanism": "TRANSPORT_LORA",
        "fromId": f"!{sender:08x}",
        "toId": "^all",
        "decoded": {
            "portnum": "POSITION_APP",
            "payload": base64.b64encode(payload).decode(),
            "position": {
                "latitudeI": LAT,
                "longitudeI": LON,
                "altitude": 53,
                "latitude": LAT / 1e7,
                "longitude": LON / 1e7,
                "raw": {"latitudeI": LAT, "longitudeI": LON, "altitude": 53},
            },
        },
    }
    packet.update(over)
    return packet, _meshpacket_b64(payload)


class TestReplayRule(unittest.TestCase):
    def test_kinds(self):
        replay = {"from": 7, "priority": "BACKGROUND", "transportMechanism": "TRANSPORT_LORA"}
        self.assertEqual(rules.classify_kind(replay, FEEDER), "replay")
        self.assertEqual(rules.classify_kind({**replay, "from": FEEDER}, FEEDER), "self")
        self.assertEqual(rules.classify_kind({**replay, "rxRssi": -90}, FEEDER), "live")

    def test_mqtt_downlink_without_rssi_is_live(self):
        mqtt = {"from": 7, "priority": "BACKGROUND", "transportMechanism": "TRANSPORT_MQTT"}
        self.assertEqual(rules.classify_kind(mqtt, FEEDER), "live")

    def test_background_priority_is_required(self):
        lora = {"from": 7, "transportMechanism": "TRANSPORT_LORA", "priority": "DEFAULT"}
        self.assertEqual(rules.classify_kind(lora, FEEDER), "live")

    def test_agrees_with_the_bot_classifier(self):
        from src.meshtastic.replay import is_replayed

        samples = [
            {"from": 7, "priority": "BACKGROUND", "transportMechanism": "TRANSPORT_LORA"},
            {"from": 7, "rxRssi": -80, "transportMechanism": "TRANSPORT_LORA"},
            {"from": FEEDER},
        ]
        for packet in samples:
            self.assertEqual(
                rules.classify_kind(packet, FEEDER) == "replay",
                is_replayed(packet, FEEDER),
                packet,
            )


class TestScrub(unittest.TestCase):
    def test_round_i(self):
        self.assertEqual(rules.round_i(LAT), 560000000)
        self.assertEqual(rules.round_i(LON), -36000000)
        self.assertEqual(rules.round_i(0), 0)
        self.assertEqual(rules.round_i(-499999), 0)

    def test_position_bytes_only_coordinates_change(self):
        old = _position_bytes(precision_bits=13)
        new = build_fixtures.scrub_position_bytes(old, "t")
        pos = mesh_pb2.Position()
        pos.ParseFromString(new)
        self.assertEqual((pos.latitude_i, pos.longitude_i), (560000000, -36000000))
        self.assertEqual((pos.altitude, pos.time, pos.precision_bits), (53, 1755077015, 13))

    def test_zero_and_absent_stay(self):
        pos = mesh_pb2.Position()
        pos.ParseFromString(
            build_fixtures.scrub_position_bytes(_position_bytes(lat=0, lon=0), "t")
        )
        self.assertEqual((pos.latitude_i, pos.longitude_i), (0, 0))
        no_coords = mesh_pb2.Position(altitude=5, time=9).SerializeToString()
        self.assertEqual(build_fixtures.scrub_position_bytes(no_coords, "t"), no_coords)

    def test_meshpacket_position_rounded_others_untouched(self):
        scrubbed = build_fixtures.scrub_meshpacket_b64(
            _meshpacket_b64(_position_bytes()), "t"
        )
        mp = mesh_pb2.MeshPacket()
        mp.ParseFromString(base64.b64decode(scrubbed))
        pos = mesh_pb2.Position()
        pos.ParseFromString(mp.decoded.payload)
        self.assertEqual((pos.latitude_i, pos.longitude_i), (560000000, -36000000))
        self.assertEqual((mp.id, mp.hop_limit), (1234, 3))
        other = _meshpacket_b64(b"hi", portnums_pb2.TEXT_MESSAGE_APP)
        self.assertEqual(build_fixtures.scrub_meshpacket_b64(other, "t"), other)
        self.assertIsNone(build_fixtures.scrub_meshpacket_b64(None, "t"))

    def test_tree_rounds_dict_copies_and_payload_together(self):
        packet, _ = _position_packet()
        build_fixtures.scrub_tree(packet, "t")
        position = packet["decoded"]["position"]
        self.assertEqual(position["latitudeI"], 560000000)
        self.assertEqual(position["raw"]["longitudeI"], -36000000)
        self.assertEqual((position["latitude"], position["longitude"]), (56.0, -3.6))
        self.assertEqual(position["altitude"], 53)
        self.assertEqual(rules.grid_violations(packet), [])
        pos = mesh_pb2.Position()
        pos.ParseFromString(base64.b64decode(packet["decoded"]["payload"]))
        self.assertEqual(pos.latitude_i, position["latitudeI"])

    def test_grid_violations_flags_unrounded(self):
        packet, _ = _position_packet()
        self.assertTrue(rules.grid_violations(packet))

    def test_secret_keys(self):
        self.assertEqual(rules.secret_keys({"a": [{"privateKey": 1}], "deviceId": 2}), ["deviceId", "privateKey"])
        self.assertEqual(rules.secret_keys({"publicKey": 1, "psk_like": 0}), ["psk_like"])


class TestTransportLabel(unittest.TestCase):
    def _labels(self, transport, **kw):
        packet = {"from": 7, "decoded": {"portnum": "POSITION_APP"}, "rxTime": 1}
        if transport:
            packet["transportMechanism"] = transport
        record = {"packet": packet, "kind": "live"}
        return rules.labels_for(record, feeder_fw="2.7.20", scheme="mac", **kw)

    def test_wifi_rows_are_labelled_lora_and_absent_are_not(self):
        self.assertIn("transport:udp-multicast", self._labels("TRANSPORT_MULTICAST_UDP"))
        self.assertFalse([x for x in self._labels("TRANSPORT_LORA") if x.startswith("transport:")])
        self.assertFalse([x for x in self._labels(None) if x.startswith("transport:")])

    def test_frozen_rows_never_get_it(self):
        self.assertFalse(
            [x for x in self._labels("TRANSPORT_MULTICAST_UDP", transport_label=False) if x.startswith("transport:")]
        )


class TestIdentityScheme(unittest.TestCase):
    def test_schemes(self):
        import zlib

        key = base64.b64encode(bytes(range(32))).decode()
        crc = zlib.crc32(bytes(range(32))) & 0xFFFFFFFF
        mac = base64.b64encode(bytes([1, 2, 0xAA, 0xBB, 0xCC, 0xDD])).decode()
        zero = base64.b64encode(bytes(6)).decode()
        self.assertEqual(rules.id_scheme(crc, {"publicKey": key}), "crc32")
        self.assertEqual(rules.id_scheme(0xAABBCCDD, {"macaddr": mac}), "mac")
        self.assertEqual(rules.id_scheme(5, {"macaddr": zero, "publicKey": key}), "neither")
        self.assertEqual(rules.id_scheme(5, None), "no_user")


class TestBuildAndCheck(unittest.TestCase):
    """End to end on a tiny fx1 capture and a tiny bot dump."""

    def _args(self, input_path, out, capture_id="t-1"):
        return build_fixtures.argparse.Namespace(
            input=str(input_path),
            capture_id=capture_id,
            short="t1",
            out=str(out),
            hop_limit=3,
            role="CLIENT",
            signature_policy=None,
            hw_model=None,
            lib_note="test lib",
            notes="tiny",
            own_node=None,
        )

    def _fx1(self, tmp: Path) -> Path:
        pkt, raw = _position_packet(sender=7)
        replay_pkt, replay_raw = _position_packet(sender=8, id=99)
        live = {**pkt, "rxRssi": -80, "id": 5}
        live.pop("priority")
        selfp = {
            "from": FEEDER,
            "id": 6,
            "fromId": "!00000064",
            "decoded": {"portnum": "TELEMETRY_APP", "telemetry": {"deviceMetrics": {"batteryLevel": 5}}},
        }
        text = {"from": 9, "id": 7, "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hello"}}
        # the replay is the live packet minus rssi, at t=1
        rows = [(live, raw, 10.0), (replay_pkt, raw, 11.0), (selfp, None, 12.0), (text, None, 13.0)]
        stem = tmp / "cap"
        with open(f"{stem}.jsonl", "w") as f:
            for packet, raw_b64, t in rows:
                f.write(json.dumps({"t_host": t, "raw_b64": raw_b64, "packet": packet}) + "\n")
        (tmp / "cap_meta.json").write_text(
            json.dumps(
                {
                    "my_info": {"myNodeNum": FEEDER, "deviceId": "SECRET"},
                    "metadata": {"firmwareVersion": "2.8.2.x", "hwModel": "XIAO", "deviceStateVersion": 25},
                    "lib": "?",
                }
            )
        )
        (tmp / "cap_nodedb.json").write_text(
            json.dumps({"!00000007": {"num": 7, "position": {"latitudeI": LAT, "longitudeI": LON, "latitude": LAT / 1e7, "longitude": LON / 1e7}}})
        )
        return tmp / "cap.jsonl"

    def _root(self, tmp: Path, capture_id="t-1") -> Path:
        root = tmp / "root"
        (root / "captures").mkdir(parents=True)
        (root / "captures.json").write_text(
            json.dumps([{"id": capture_id, "short": "t1", "status": "captured", "path": f"captures/{capture_id}", "purpose": "t"},
                        {"id": "later", "status": "pending", "purpose": "p"}])
        )
        (root / "subset.json").write_text("[]")
        return root

    def test_fx1_build_scrubs_drops_text_and_passes_the_check(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            src = self._fx1(tmp)
            root = self._root(tmp)
            out = root / "captures" / "t-1"
            build_fixtures.build(self._args(src, out))
            records = build_fixtures.load_capture_records(out)
            self.assertEqual([r["kind"] for r in records], ["live", "replay", "self"])
            self.assertEqual([r["src_line"] for r in records], [1, 2, 3])  # the text message is gone
            self.assertEqual(rules.grid_violations([r["packet"] for r in records]), [])
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["counts"]["by_kind"], {"live": 1, "replay": 1, "self": 1})
            self.assertEqual(manifest["scrub"]["positions_rounded"], 2)
            self.assertNotIn("SECRET", (out / "manifest.json").read_text())
            ok, problems = check_fixtures.check_tree(root)
            self.assertEqual(problems, [])
            self.assertTrue(any(line.startswith("OK t-1") for line in ok))

            first = {p.name: p.read_bytes() for p in out.iterdir()}
            build_fixtures.build(self._args(src, out))
            self.assertEqual(first, {p.name: p.read_bytes() for p in out.iterdir()})

    def test_check_names_the_line_of_an_unrounded_position(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            root = self._root(tmp)
            out = root / "captures" / "t-1"
            build_fixtures.build(self._args(self._fx1(tmp), out))
            lines = (out / "capture.jsonl").read_text().splitlines()
            rec = json.loads(lines[0])
            rec["packet"]["decoded"]["position"]["latitudeI"] = LAT
            lines[0] = json.dumps(rec)
            (out / "capture.jsonl").write_text("\n".join(lines) + "\n")
            _, problems = check_fixtures.check_tree(root)
            self.assertTrue(any("capture.jsonl:1" in p and "grid" in p for p in problems), problems)

    def test_check_rejects_a_wrong_kind_and_a_secret_key(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            root = self._root(tmp)
            out = root / "captures" / "t-1"
            build_fixtures.build(self._args(self._fx1(tmp), out))
            lines = (out / "capture.jsonl").read_text().splitlines()
            rec = json.loads(lines[1])
            rec["kind"] = "live"
            rec["packet"]["privateKey"] = "x"
            lines[1] = json.dumps(rec)
            (out / "capture.jsonl").write_text("\n".join(lines) + "\n")
            _, problems = check_fixtures.check_tree(root)
            joined = "\n".join(problems)
            self.assertIn("capture.jsonl:2", joined)
            self.assertIn("replay rule", joined)
            self.assertIn("secret-looking keys", joined)

    @staticmethod
    def _text_last_received(sender: int) -> dict:
        data = {"portnum": "TEXT_MESSAGE_APP", "payload": "c3ludGhldGlj", "text": "synthetic"}
        return {"from": sender, "to": 4294967295, "id": 41, "decoded": data, "raw": {"from": sender, "decoded": dict(data)}}

    def test_check_rejects_third_party_text_in_a_nodedb(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            root = self._root(tmp)
            out = root / "captures" / "t-1"
            build_fixtures.build(self._args(self._fx1(tmp), out))
            self.assertEqual(check_fixtures.check_tree(root)[1], [])
            path = out / "nodedb.json"
            nodedb = json.loads(path.read_text())
            nodedb["!00000007"]["lastReceived"] = self._text_last_received(7)
            path.write_text(json.dumps(nodedb))
            _, problems = check_fixtures.check_tree(root)
            self.assertTrue(any("nodedb.json" in p and "text message" in p for p in problems), problems)
            # the feeder's own text in its NodeDB is allowed
            nodedb["!00000007"]["lastReceived"] = self._text_last_received(FEEDER)
            path.write_text(json.dumps(nodedb))
            _, problems = check_fixtures.check_tree(root)
            self.assertFalse(any("text message" in p for p in problems), problems)

    def test_build_drops_third_party_text_from_a_nodedb_and_keeps_own(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            root = self._root(tmp)
            src = self._fx1(tmp)
            stem = tmp / "cap_nodedb.json"
            nodedb = json.loads(stem.read_text())
            nodedb["!00000007"]["lastReceived"] = self._text_last_received(7)
            nodedb["!00000008"] = {"num": 8, "lastReceived": self._text_last_received(FEEDER)}
            stem.write_text(json.dumps(nodedb))
            out = root / "captures" / "t-1"
            build_fixtures.build(self._args(src, out))
            built = json.loads((out / "nodedb.json").read_text())
            self.assertNotIn("lastReceived", built["!00000007"])
            self.assertIn("lastReceived", built["!00000008"])
            self.assertNotIn("c3ludGhldGlj", json.dumps(built["!00000007"]))
            self.assertEqual(check_fixtures.check_tree(root)[1], [])

    def test_bot_dump_input_orders_by_captured_at_and_labels_replay_folder(self):
        with tempfile.TemporaryDirectory() as t:
            dump = Path(t) / "data"
            pkt, raw = _position_packet(sender=8, id=2)
            replay = {k: v for k, v in pkt.items()}
            live, live_raw = _position_packet(sender=7, id=1)
            live["rxRssi"] = -70
            live["decoded"]["position"]["raw"] = "latitude_i: 1"  # str(proto) as the bot dump writes it
            meta = {"feeder_num": FEEDER, "feeder_fw": "2.8.2.x", "lib_version": "2.7.11"}
            for folder, packet, raw_b64, stamp in (
                ("packets", live, live_raw, "2026-11-08T14:00:02+00:00"),
                ("replay", replay, raw, "2026-11-08T14:00:01+00:00"),
            ):
                d = dump / folder / "POSITION_APP"
                d.mkdir(parents=True)
                (d / "x.json").write_text(
                    json.dumps({"packet": packet, "raw_b64": raw_b64, "meta": {**meta, "captured_at": stamp}})
                )
            root = self._root(Path(t))
            out = root / "captures" / "t-1"
            build_fixtures.build(self._args(dump, out))
            records = build_fixtures.load_capture_records(out)
            self.assertEqual([r["kind"] for r in records], ["replay", "live"])
            self.assertEqual([r["packet"]["id"] for r in records], [2, 1])
            self.assertNotIn("raw", json.dumps(records[1]["packet"]["decoded"]["position"]))
            self.assertEqual(records[1]["t_host"] - records[0]["t_host"], 1.0)


if __name__ == "__main__":
    unittest.main()
