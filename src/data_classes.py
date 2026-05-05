"""Bot domain model.

Protocol-agnostic. Translation from a Meshtastic node dict into one of these
lives in :mod:`src.meshtastic.translation`.
"""

from datetime import datetime
from typing import Optional


class MeshNode:
    class User:
        id: str
        long_name: str
        short_name: str
        macaddr: str
        hw_model: str
        public_key: str

        def __init__(
            self,
            node_id: str = "",
            long_name: str = "",
            short_name: str = "",
            macaddr: str = "",
            hw_model: str = "",
            public_key: str = "",
        ):
            self.id = node_id
            self.long_name = long_name
            self.short_name = short_name
            self.macaddr = macaddr
            self.hw_model = hw_model
            self.public_key = public_key

    class Position:
        logged_time: datetime
        altitude: float
        reported_time: datetime
        location_source: str
        latitude: float
        longitude: float

        def __init__(
            self,
            logged_time: datetime,
            latitude: float = 0.0,
            longitude: float = 0.0,
            altitude: float = 0,
            reported_time: datetime = 0,
            location_source: str = "",
        ):
            self.logged_time = logged_time
            self.latitude = latitude
            self.longitude = longitude
            self.altitude = altitude
            self.reported_time = reported_time
            self.location_source = location_source

    class DeviceMetrics:
        logged_time: datetime
        battery_level: int
        voltage: float
        channel_utilization: float
        air_util_tx: float
        uptime_seconds: int

        def __init__(
            self,
            logged_time: datetime,
            battery_level: int = 0,
            voltage: float = 0.0,
            channel_utilization: float = 0.0,
            air_util_tx: float = 0.0,
            uptime_seconds: int = 0,
        ):
            self.logged_time = logged_time
            self.battery_level = battery_level
            self.voltage = voltage
            self.channel_utilization = channel_utilization
            self.air_util_tx = air_util_tx
            self.uptime_seconds = uptime_seconds

    user: Optional[User]
    position: Optional[Position]
    device_metrics: Optional[DeviceMetrics]
    is_favorite: bool

    @classmethod
    def from_dict(cls, node_data: dict) -> "MeshNode":
        # Backward-compatible shim: delegate to the Meshtastic adapter so
        # existing call-sites and tests keep working. New code should call
        # ``src.meshtastic.translation.node_dict_to_mesh_node`` directly.
        from src.meshtastic.translation import node_dict_to_mesh_node

        return node_dict_to_mesh_node(node_data)
