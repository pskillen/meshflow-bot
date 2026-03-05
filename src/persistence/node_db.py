import abc
from datetime import datetime
import sqlite3

from src.data_classes import MeshNode
from src.persistence import BaseSqlitePersistenceStore


class AbstractNodeDB(abc.ABC):

    def store_node(self, node: MeshNode):
        self.store_user(node.user)
        if hasattr(node, 'position') and node.position:
            self.store_position(node.user.id, node.position)
        if hasattr(node, 'device_metrics') and node.device_metrics:
            self.store_device_metrics(node.user.id, node.device_metrics)

    @abc.abstractmethod
    def get_by_id(self, node_id: str) -> MeshNode.User | None:
        pass

    @abc.abstractmethod
    def get_by_short_name(self, short_name: str) -> MeshNode.User | None:
        pass

    @abc.abstractmethod
    def list_nodes(self) -> list[MeshNode.User]:
        pass

    @abc.abstractmethod
    def store_user(self, node_user: MeshNode.User):
        pass

    @abc.abstractmethod
    def store_position(self, node_id: str, position: MeshNode.Position):
        pass

    @abc.abstractmethod
    def get_last_position(self, node_id: str) -> MeshNode.Position | None:
        pass

    @abc.abstractmethod
    def get_position_log(self, node_id: str,
                         start: datetime,
                         end: datetime) -> list[MeshNode.Position]:
        pass

    @abc.abstractmethod
    def store_device_metrics(self, node_id: str, device_metrics: MeshNode.DeviceMetrics):
        pass

    @abc.abstractmethod
    def get_last_device_metrics(self, node_id: str) -> MeshNode.DeviceMetrics | None:
        pass

    @abc.abstractmethod
    def get_device_metrics_log(self, node_id: str,
                               start: datetime,
                               end: datetime) -> list[MeshNode.DeviceMetrics]:
        pass


class InMemoryNodeDB(AbstractNodeDB):
    def __init__(self):
        self.nodes = {}
        self.positions = dict[str, list[MeshNode.Position]]()
        self.device_metrics = dict[str, list[MeshNode.DeviceMetrics]]()

    def store_user(self, node_user: MeshNode.User):
        self.nodes[node_user.id] = node_user

    def store_position(self, node_id: str, position: MeshNode.Position):
        if node_id not in self.positions:
            self.positions[node_id] = []
        self.positions[node_id].append(position)

    def store_device_metrics(self, node_id: str, device_metrics: MeshNode.DeviceMetrics):
        if node_id not in self.device_metrics:
            self.device_metrics[node_id] = []
        self.device_metrics[node_id].append(device_metrics)

    def get_by_id(self, node_id: str) -> MeshNode.User | None:
        return self.nodes.get(node_id)

    def get_by_short_name(self, short_name: str) -> MeshNode.User | None:
        for node in self.nodes.values():
            if node.short_name.lower() == short_name.lower():
                return node
        return None

    def list_nodes(self) -> list[MeshNode.User]:
        return list(self.nodes.values())

    def get_last_position(self, node_id: str) -> MeshNode.Position | None:
        if node_id in self.positions and self.positions[node_id]:
            return self.positions[node_id][-1]
        return None

    def get_position_log(self, node_id: str, start: datetime, end: datetime) -> list[
        MeshNode.Position]:
        if node_id in self.positions:
            return [pos for pos in self.positions[node_id] if start <= pos.logged_time <= end]
        return []

    def get_last_device_metrics(self, node_id: str) -> MeshNode.DeviceMetrics | None:
        if node_id in self.device_metrics and self.device_metrics[node_id]:
            return self.device_metrics[node_id][-1]
        return None

    def get_device_metrics_log(self, node_id: str, start: datetime, end: datetime) -> list[
        MeshNode.DeviceMetrics]:
        if node_id in self.device_metrics:
            return [metrics for metrics in self.device_metrics[node_id] if start <= metrics.logged_time <= end]
        return []


class SqliteNodeDB(BaseSqlitePersistenceStore, AbstractNodeDB):

    def _initialize_db(self):
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    short_name TEXT,
                    long_name TEXT,
                    macaddr TEXT,
                    hw_model TEXT,
                    public_key TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    node_id TEXT,
                    logged_time DATETIME,
                    reported_time DATETIME,
                    latitude REAL,
                    longitude REAL,
                    altitude REAL,
                    location_source TEXT,
                    FOREIGN KEY(node_id) REFERENCES nodes(id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS device_metrics (
                    node_id TEXT,
                    logged_time DATETIME,
                    battery_level INTEGER,
                    voltage REAL,
                    channel_utilization REAL,
                    air_util_tx REAL,
                    uptime_seconds INTEGER,
                    FOREIGN KEY(node_id) REFERENCES nodes(id)
                )
            ''')
            conn.commit()

    def store_user(self, node_user: MeshNode.User):
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO nodes (id, short_name, long_name, macaddr, hw_model, public_key)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (node_user.id, node_user.short_name, node_user.long_name, node_user.macaddr, node_user.hw_model,
                  node_user.public_key))
            conn.commit()

    def store_position(self, node_id: str, position: MeshNode.Position):
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO positions (node_id, logged_time, reported_time, latitude, longitude, altitude, location_source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (node_id, position.logged_time, position.reported_time, position.latitude, position.longitude,
                  position.altitude, position.location_source))
            conn.commit()

    def store_device_metrics(self, node_id: str, device_metrics: MeshNode.DeviceMetrics):
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO device_metrics (node_id, logged_time, battery_level, voltage, channel_utilization, air_util_tx, uptime_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (node_id, device_metrics.logged_time, device_metrics.battery_level, device_metrics.voltage,
                  device_metrics.channel_utilization, device_metrics.air_util_tx, device_metrics.uptime_seconds))
            conn.commit()

    def get_by_id(self, node_id: str) -> MeshNode.User | None:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, short_name, long_name, macaddr, hw_model, public_key FROM nodes WHERE id = ?',
                           (node_id,))
            row = cursor.fetchone()
            if row:
                return MeshNode.User(node_id=row[0], short_name=row[1], long_name=row[2], macaddr=row[3],
                                     hw_model=row[4], public_key=row[5])
            return None

    def get_by_short_name(self, short_name: str) -> MeshNode.User | None:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, short_name, long_name, macaddr, hw_model, public_key FROM nodes WHERE short_name = ? COLLATE NOCASE',
                (short_name,))
            row = cursor.fetchone()
            if row:
                return MeshNode.User(node_id=row[0], short_name=row[1], long_name=row[2], macaddr=row[3],
                                     hw_model=row[4], public_key=row[5])
            return None

    def list_nodes(self) -> list[MeshNode.User]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, short_name, long_name, macaddr, hw_model, public_key FROM nodes')
            rows = cursor.fetchall()
            return [MeshNode.User(node_id=row[0], short_name=row[1], long_name=row[2], macaddr=row[3],
                                  hw_model=row[4], public_key=row[5]) for row in rows]

    def get_last_position(self, node_id: str) -> MeshNode.Position | None:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT logged_time, reported_time, latitude, longitude, altitude, location_source
                FROM positions
                WHERE node_id = ?
                ORDER BY logged_time DESC
                LIMIT 1
            ''', (node_id,))
            row = cursor.fetchone()
            if row:
                return MeshNode.Position(logged_time=row[0], reported_time=row[1], latitude=row[2], longitude=row[3],
                                         altitude=row[4], location_source=row[5])
            return None

    def get_position_log(self, node_id: str, start: datetime, end: datetime) -> list[
        MeshNode.Position]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT logged_time, reported_time, latitude, longitude, altitude, location_source
                FROM positions
                WHERE node_id = ? AND logged_time BETWEEN ? AND ?
                ORDER BY logged_time
            ''', (node_id, start, end))
            rows = cursor.fetchall()
            return [MeshNode.Position(logged_time=row[0], reported_time=row[1], latitude=row[2], longitude=row[3],
                                      altitude=row[4], location_source=row[5]) for row in rows]

    def get_last_device_metrics(self, node_id: str) -> MeshNode.DeviceMetrics | None:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT logged_time, battery_level, voltage, channel_utilization, air_util_tx, uptime_seconds
                FROM device_metrics
                WHERE node_id = ?
                ORDER BY logged_time DESC
                LIMIT 1
            ''', (node_id,))
            row = cursor.fetchone()
            if row:
                return MeshNode.DeviceMetrics(logged_time=row[0], battery_level=row[1], voltage=row[2],
                                              channel_utilization=row[3], air_util_tx=row[4], uptime_seconds=row[5])
            return None

    def get_device_metrics_log(self, node_id: str, start: datetime, end: datetime) -> list[
        MeshNode.DeviceMetrics]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT logged_time, battery_level, voltage, channel_utilization, air_util_tx, uptime_seconds
                FROM device_metrics
                WHERE node_id = ? AND logged_time BETWEEN ? AND ?
                ORDER BY logged_time
            ''', (node_id, start, end))
            rows = cursor.fetchall()
            return [MeshNode.DeviceMetrics(logged_time=row[0], battery_level=row[1], voltage=row[2],
                                           channel_utilization=row[3], air_util_tx=row[4], uptime_seconds=row[5]) for
                    row in rows]
