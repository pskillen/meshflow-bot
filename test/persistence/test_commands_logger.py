from datetime import datetime, timezone, timedelta
import os
import sqlite3
import unittest
from unittest.mock import MagicMock

from src.commands.command import AbstractCommand
from src.persistence.commands_logger import SqliteCommandLogger
from src.responders.responder import AbstractResponder


class TestSqliteCommandLogger(unittest.TestCase):
    def setUp(self):
        self.db_path = 'test_commands.sqlite'
        self.logger = SqliteCommandLogger(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_initialize_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='command_log'")
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unknown_requests'")
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='responder_log'")
            self.assertIsNotNone(cursor.fetchone())

    def test_log_command(self):
        command_instance = MagicMock(spec=AbstractCommand)
        command_instance.get_command_for_logging.return_value = ('base_cmd', ['sub_cmd1', 'sub_cmd2'], 'arg1 arg2')
        self.logger.log_command('sender1', command_instance, 'message')

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM command_log WHERE sender_id='sender1'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], 'base_cmd')
            self.assertEqual(row[2], 'sub_cmd1 sub_cmd2')
            self.assertEqual(row[3], 'arg1 arg2')
            self.assertEqual(row[5], 'AbstractCommand')

    def test_log_unknown_request(self):
        self.logger.log_unknown_request('sender1', 'unknown message')

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM unknown_requests WHERE sender_id='sender1'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], 'unknown message')

    def test_log_responder_handled(self):
        responder_instance = MagicMock(spec=AbstractResponder)
        self.logger.log_responder_handled('sender1', responder_instance, 'response message')

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM responder_log WHERE sender_id='sender1'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], 'response message')
            self.assertEqual(row[3], 'AbstractResponder')

    def test_get_command_history(self):
        command_instance = MagicMock(spec=AbstractCommand)
        command_instance.get_command_for_logging.return_value = ('base_cmd', ['sub_cmd1', 'sub_cmd2'], 'arg1 arg2')
        self.logger.log_command('sender1', command_instance, 'message')

        since = datetime.now(timezone.utc) - timedelta(days=1)
        history = self.logger.get_command_history(since=since)
        self.assertGreater(len(history), 0)
        for key in ('sender_id', 'base_command', 'timestamp'):
            self.assertIn(key, history[0])

    def test_get_unknown_command_history(self):
        self.logger.log_unknown_request('sender1', 'unknown message')

        since = datetime.now(timezone.utc) - timedelta(days=1)
        history = self.logger.get_unknown_command_history(since=since)
        self.assertGreater(len(history), 0)
        for key in ('sender_id', 'message', 'timestamp'):
            self.assertIn(key, history[0])

    def test_get_responder_history(self):
        responder_instance = MagicMock(spec=AbstractResponder)
        self.logger.log_responder_handled('sender1', responder_instance, 'response message')

        since = datetime.now(timezone.utc) - timedelta(days=1)
        history = self.logger.get_responder_history(since=since)
        self.assertGreater(len(history), 0)
        for key in ('sender_id', 'responder_class', 'timestamp'):
            self.assertIn(key, history[0])


if __name__ == '__main__':
    unittest.main()
