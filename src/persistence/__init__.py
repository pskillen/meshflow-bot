import abc
import logging
import sqlite3
import threading
from pathlib import Path


class BaseSqlitePersistenceStore(abc.ABC):
    db_path: Path
    _conn: sqlite3.Connection | None
    _lock: threading.RLock

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._conn = None
        self._lock = threading.RLock()
        self._initialize_db()
        if self.db_path.is_relative_to(Path.cwd()):
            path_string = self.db_path.relative_to(Path.cwd())
        else:
            path_string = self.db_path
        logging.info(f"Connected to {self.__class__.__name__} DB at {path_string}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a persistent database connection."""
        if self._conn is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0
            )
            # Enable WAL mode for better concurrency
            try:
                cursor = self._conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
            except Exception:
                # WAL mode is optional, continue without it if it fails
                pass
        else:
            # Validate existing connection is still viable
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
            except sqlite3.ProgrammingError:
                # Connection is broken, reset it
                self._conn = None
                return self._get_connection()  # Recursive call to create a new one
        
        return self._conn

    @abc.abstractmethod
    def _initialize_db(self):
        pass
