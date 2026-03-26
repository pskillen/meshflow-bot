import abc
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from src.persistence import BaseSqlitePersistenceStore


class AbstractCommandLogger(abc.ABC):

    @abc.abstractmethod
    def log_command(self, sender_id: str, command_instance, message: str) -> None:
        pass

    @abc.abstractmethod
    def log_unknown_request(self, sender_id: str, message: str) -> None:
        pass

    @abc.abstractmethod
    def log_responder_handled(self, sender_id: str, responder_instance, message_text: str) -> None:
        pass

    @abc.abstractmethod
    def get_command_history(self, since: datetime, sender_id: str = None) -> pd.DataFrame:
        pass

    @abc.abstractmethod
    def get_unknown_command_history(self, since: datetime, sender_id: str = None) -> pd.DataFrame:
        pass

    @abc.abstractmethod
    def get_responder_history(self, since: datetime, sender_id: str = None) -> pd.DataFrame:
        pass


class SqliteCommandLogger(AbstractCommandLogger, BaseSqlitePersistenceStore):

    def _initialize_db(self):
        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS command_log (
                    sender_id TEXT,
                    base_command TEXT,
                    sub_commands TEXT,
                    args TEXT,
                    timestamp TEXT,
                    handler_class TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS unknown_requests (
                    sender_id TEXT,
                    message TEXT,
                    timestamp TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS responder_log (
                    sender_id TEXT,
                    message TEXT,
                    timestamp TEXT,
                    responder_class TEXT
                )
            ''')
            conn.commit()

    def log_command(self, sender_id: str, command_instance, message: str) -> None:
        base_cmd, subcommands, args = command_instance.get_command_for_logging(message)
        subcommands_str = ' '.join(subcommands) if subcommands else None

        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO command_log (sender_id, base_command, sub_commands, args, timestamp, handler_class)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (sender_id, base_cmd, subcommands_str, args, datetime.now(timezone.utc).isoformat(),
                  command_instance.__class__.__name__))
            conn.commit()

    def log_responder_handled(self, sender_id: str, responder_instance, message_text: str) -> None:
        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO responder_log (sender_id, message, timestamp, responder_class)
                VALUES (?, ?, ?, ?)
            ''', (sender_id, message_text, datetime.now(timezone.utc).isoformat(), responder_instance.__class__.__name__))
            conn.commit()

    def log_unknown_request(self, sender_id: str, message: str) -> None:
        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO unknown_requests (sender_id, message, timestamp)
                VALUES (?, ?, ?)
            ''', (sender_id, message, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def get_command_history(self, since: datetime, sender_id: str = None) -> pd.DataFrame:
        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            if sender_id:
                cursor.execute('''
                    SELECT sender_id, base_command, timestamp FROM command_log
                    WHERE sender_id = ? AND timestamp >= ?
                ''', (sender_id, since.isoformat()))
            else:
                cursor.execute('''
                    SELECT sender_id, base_command, timestamp FROM command_log
                    WHERE timestamp >= ?
                ''', (since.isoformat(),))
            rows = cursor.fetchall()
            return pd.DataFrame(rows, columns=['sender_id', 'base_command', 'timestamp'])

    def get_unknown_command_history(self, since: datetime, sender_id: str = None) -> pd.DataFrame:
        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            if sender_id:
                cursor.execute('''
                    SELECT sender_id, message, timestamp FROM unknown_requests
                    WHERE sender_id = ? AND timestamp >= ?
                ''', (sender_id, since.isoformat()))
            else:
                cursor.execute('''
                    SELECT sender_id, message, timestamp FROM unknown_requests
                    WHERE timestamp >= ?
                ''', (since.isoformat(),))
            rows = cursor.fetchall()
            return pd.DataFrame(rows, columns=['sender_id', 'message', 'timestamp'])

    def get_responder_history(self, since: datetime, sender_id: str = None) -> pd.DataFrame:
        conn = self._get_connection()
        with self._lock:
            cursor = conn.cursor()
            if sender_id:
                cursor.execute('''
                    SELECT sender_id, responder_class, timestamp FROM responder_log
                    WHERE sender_id = ? AND timestamp >= ?
                ''', (sender_id, since.isoformat()))
            else:
                cursor.execute('''
                    SELECT sender_id, responder_class, timestamp FROM responder_log
                    WHERE timestamp >= ?
                ''', (since.isoformat(),))
            rows = cursor.fetchall()
            return pd.DataFrame(rows, columns=['sender_id', 'responder_class', 'timestamp'])

