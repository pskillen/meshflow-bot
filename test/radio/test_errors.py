"""Tests for the error-boundary helpers in :mod:`src.radio.errors`."""

import logging
import unittest

from src.radio.errors import (
    ErrorCounter,
    call_safely,
    get_global_error_counter,
    safe_callback,
)


class TestErrorCounter(unittest.TestCase):
    def test_increment_returns_new_count(self):
        counter = ErrorCounter()
        self.assertEqual(counter.increment("foo"), 1)
        self.assertEqual(counter.increment("foo"), 2)
        self.assertEqual(counter.increment("bar"), 1)

    def test_get_returns_zero_for_unknown(self):
        counter = ErrorCounter()
        self.assertEqual(counter.get("missing"), 0)

    def test_snapshot_is_isolated_copy(self):
        counter = ErrorCounter()
        counter.increment("foo")
        snap = counter.snapshot()
        counter.increment("foo")
        self.assertEqual(snap, {"foo": 1})
        self.assertEqual(counter.get("foo"), 2)


class TestSafeCallback(unittest.TestCase):
    def test_returns_value_on_success(self):
        @safe_callback("ok")
        def fn(x):
            return x * 2

        self.assertEqual(fn(3), 6)

    def test_swallows_exceptions_and_increments_counter(self):
        counter = ErrorCounter()
        log = logging.getLogger("test_safe_callback_silent")
        log.addHandler(logging.NullHandler())

        @safe_callback("boom", counter=counter, log=log)
        def fn():
            raise ValueError("nope")

        self.assertIsNone(fn())
        self.assertEqual(counter.get("boom"), 1)

    def test_default_counter_is_global(self):
        before = get_global_error_counter().get("test_default_counter_is_global")

        @safe_callback("test_default_counter_is_global")
        def fn():
            raise RuntimeError("x")

        fn()
        after = get_global_error_counter().get("test_default_counter_is_global")
        self.assertEqual(after - before, 1)


class TestCallSafely(unittest.TestCase):
    def test_returns_value_on_success(self):
        self.assertEqual(call_safely("ok", lambda x: x + 1, 5), 6)

    def test_swallows_and_counts(self):
        counter = ErrorCounter()
        log = logging.getLogger("test_call_safely_silent")
        log.addHandler(logging.NullHandler())

        def boom():
            raise KeyError("nope")

        self.assertIsNone(call_safely("k", boom, counter=counter, log=log))
        self.assertEqual(counter.get("k"), 1)


if __name__ == "__main__":
    unittest.main()
