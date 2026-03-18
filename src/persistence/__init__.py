import abc
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


class BaseSqlitePersistenceStore(abc.ABC):
    db_path: Path

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._initialize_db()
        if self.db_path.is_relative_to(Path.cwd()):
            path_string = self.db_path.relative_to(Path.cwd())
        else:
            path_string = self.db_path
        logging.info(f"Connected to {self.__class__.__name__} DB at {path_string}")

    @contextmanager
    def _get_connection(self):
        """Returns a thread-safe sqlite3 connection and ensures it is closed."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()

    @abc.abstractmethod
    def _initialize_db(self):
        pass
