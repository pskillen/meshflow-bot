"""Unit tests for MeshCore path hash splitting (_path_hashes)."""

from src.meshcore.serializers import _path_hashes


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
