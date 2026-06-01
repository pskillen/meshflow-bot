"""Unit tests for MeshCore path hash splitting (_path_hashes) and ingest envelope."""

from src.meshcore.serializers import MeshCorePacketSerializer, _path_hashes


def test_path_hashes_two_byte_default():
    payload = {"path": "f3bcf1a2b3c4", "path_hash_size": 2}
    assert _path_hashes(payload) == ["f3bc", "f1a2", "b3c4"]


def test_path_hashes_one_byte():
    payload = {"path": "aabbcc", "path_hash_size": 1}
    assert _path_hashes(payload) == ["aa", "bb", "cc"]


def test_path_hashes_three_byte():
    payload = {"path": "aabbccddeeff", "path_hash_size": 3}
    assert _path_hashes(payload) == ["aabbcc", "ddeeff"]


def test_path_hashes_missing_path_returns_none():
    assert _path_hashes({"path_len": 2}) is None
    assert _path_hashes({}) is None


def test_path_hashes_list_passthrough():
    payload = {"path": ["aa", "bb"]}
    assert _path_hashes(payload) == ["aa", "bb"]


def test_channel_message_envelope_includes_path_hash_size_and_mode():
    serializer = MeshCorePacketSerializer()
    envelope = {
        "protocol": "meshcore",
        "event_type": "channel_message",
        "payload": {
            "text": "hi",
            "channel_idx": 0,
            "path": "aabb",
            "path_hash_size": 1,
            "path_hash_mode": 2,
            "recv_time": 1700000000.0,
        },
        "attributes": {},
    }
    result = serializer.serialise_raw_packet(envelope)
    assert result["path_hashes"] == ["aa", "bb"]
    assert result["path_hash_size"] == 1
    assert result["path_hash_mode"] == 2


def test_contact_message_envelope_defaults_path_hash_size_to_two():
    serializer = MeshCorePacketSerializer()
    envelope = {
        "protocol": "meshcore",
        "event_type": "contact_message",
        "payload": {
            "text": "dm",
            "pubkey_prefix": "ab" * 6,
            "channel_idx": 0,
            "path": "f3bcf1",
            "recv_time": 1700000000.0,
        },
        "attributes": {},
    }
    result = serializer.serialise_raw_packet(envelope)
    assert result["path_hash_size"] == 2
    assert result["path_hash_mode"] is None
