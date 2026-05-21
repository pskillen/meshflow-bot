import unittest
from datetime import datetime, timedelta, timezone

from src.helpers import pretty_print_last_heard, safe_encode_node_name


class TestPrettyPrintLastHeard(unittest.TestCase):

    def test_seconds_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = now - timedelta(seconds=30)
        self.assertEqual(pretty_print_last_heard(timestamp), "30s ago")

    def test_minutes_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = now - timedelta(minutes=5)
        self.assertEqual(pretty_print_last_heard(timestamp), "5m ago")

    def test_hours_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = now - timedelta(hours=2)
        self.assertEqual(pretty_print_last_heard(timestamp), "2h ago")

    def test_days_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = now - timedelta(days=3)
        self.assertEqual(pretty_print_last_heard(timestamp), "3d ago")

    def test_timestamp_seconds_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = int((now - timedelta(seconds=45)).timestamp())
        self.assertEqual(pretty_print_last_heard(timestamp), "45s ago")

    def test_timestamp_minutes_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = int((now - timedelta(minutes=10)).timestamp())
        self.assertEqual(pretty_print_last_heard(timestamp), "10m ago")

    def test_timestamp_hours_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = int((now - timedelta(hours=1)).timestamp())
        self.assertEqual(pretty_print_last_heard(timestamp), "1h ago")

    def test_timestamp_days_ago(self):
        now = datetime.now(timezone.utc)
        timestamp = int((now - timedelta(days=1)).timestamp())
        self.assertEqual(pretty_print_last_heard(timestamp), "1d ago")

    def test_edge_case_now(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(pretty_print_last_heard(now), "0s ago")

    def test_edge_case_future(self):
        now = datetime.now(timezone.utc)
        future_time = now + timedelta(seconds=10)
        self.assertEqual(pretty_print_last_heard(future_time), "0s ago")

    def test_never_when_none(self):
        self.assertEqual(pretty_print_last_heard(None), "never")


class TestSafeEncodeNodeName(unittest.TestCase):
    def test_ascii_unchanged(self):
        self.assertEqual(safe_encode_node_name("Node A"), "Node A")

    def test_non_ascii_percent_encoded(self):
        self.assertEqual(safe_encode_node_name("café"), "caf%C3%A9")


if __name__ == "__main__":
    unittest.main()
