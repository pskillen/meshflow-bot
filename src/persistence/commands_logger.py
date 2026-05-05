import abc
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.persistence import BaseSqlitePersistenceStore


def _sqlite_rows_to_dicts(rows: list[tuple], columns: list[str]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


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
    def get_command_history(self, since: datetime, sender_id: str = None) -> list[dict[str, Any]]:
        pass

    @abc.abstractmethod
    def get_unknown_command_history(self, since: datetime, sender_id: str = None) -> list[dict[str, Any]]:
        pass

    @abc.abstractmethod
    def get_responder_history(self, since: datetime, sender_id: str = None) -> list[dict[str, Any]]:
        pass


class SqliteCommandLogger(AbstractCommandLogger, BaseSqlitePersistenceStore):

    def _initialize_db(self):
        with sqlite3.connect(self.db_path) as conn:
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

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO command_log (sender_id, base_command, sub_commands, args, timestamp, handler_class)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (sender_id, base_cmd, subcommands_str, args, datetime.now(timezone.utc).isoformat(),
                  command_instance.__class__.__name__))
            conn.commit()

    def log_responder_handled(self, sender_id: str, responder_instance, message_text: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO responder_log (sender_id, message, timestamp, responder_class)
                VALUES (?, ?, ?, ?)
            ''', (sender_id, message_text, datetime.now(timezone.utc).isoformat(), responder_instance.__class__.__name__))
            conn.commit()

    def log_unknown_request(self, sender_id: str, message: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO unknown_requests (sender_id, message, timestamp)
                VALUES (?, ?, ?)
            ''', (sender_id, message, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def get_command_history(self, since: datetime, sender_id: str = None) -> list[dict[str, Any]]:
        columns = ['sender_id', 'base_command', 'timestamp']
        with sqlite3.connect(self.db_path) as conn:
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
            return _sqlite_rows_to_dicts(rows, columns)

    def get_unknown_command_history(self, since: datetime, sender_id: str = None) -> list[dict[str, Any]]:
        columns = ['sender_id', 'message', 'timestamp']
        with sqlite3.connect(self.db_path) as conn:
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
            return _sqlite_rows_to_dicts(rows, columns)

    def get_responder_history(self, since: datetime, sender_id: str = None) -> list[dict[str, Any]]:
        columns = ['sender_id', 'responder_class', 'timestamp']
        with sqlite3.connect(self.db_path) as conn:
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
            return _sqlite_rows_to_dicts(rows, columns)
