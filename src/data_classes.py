from datetime import datetime, timezone
from typing import Optional


class MeshNode:
    class User:

        def __init__(self,
                     node_id: str = '',
                     long_name: str = '',
                     short_name: str = '',
                     macaddr: str = '',
                     hw_model: str = '',
                     public_key: str = ''):
            self.id = node_id
            self.long_name = long_name
            self.short_name = short_name
            self.macaddr = macaddr
            self.hw_model = hw_model
            self.public_key = public_key

        def __eq__(self, other):
            if not isinstance(other, MeshNode.User):
                return False
            return (self.id == other.id and
                    self.long_name == other.long_name and
                    self.short_name == other.short_name and
                    self.macaddr == other.macaddr and
                    self.hw_model == other.hw_model and
                    self.public_key == other.public_key)

        id: str
        long_name: str
        short_name: str
        macaddr: str
        hw_model: str
        public_key: str

    class Position:

        def __init__(self,
                     logged_time: datetime,
                     latitude: float = 0.0,
                     longitude: float = 0.0,
                     altitude: float = 0,
                     reported_time: datetime = 0,
                     location_source: str = ''):
            self.logged_time = logged_time
            self.latitude = latitude
            self.longitude = longitude
            self.altitude = altitude
            self.reported_time = reported_time
            self.location_source = location_source

        logged_time: datetime
        altitude: float
        reported_time: datetime
        location_source: str
        latitude: float
        longitude: float

    class DeviceMetrics:

        def __init__(self,
                     logged_time: datetime,
                     battery_level: int = 0,
                     voltage: float = 0.0,
                     channel_utilization: float = 0.0,
                     air_util_tx: float = 0.0,
                     uptime_seconds: int = 0):
            self.logged_time = logged_time
            self.battery_level = battery_level
            self.voltage = voltage
            self.channel_utilization = channel_utilization
            self.air_util_tx = air_util_tx
            self.uptime_seconds = uptime_seconds

        logged_time: datetime
        battery_level: int
        voltage: float
        channel_utilization: float
        air_util_tx: float
        uptime_seconds: int

    user: Optional[User]
    position: Optional[Position]
    device_metrics: Optional[DeviceMetrics]
    is_favorite: bool

    @classmethod
    def from_dict(cls, node_data: dict):
        user_data = node_data.get('user', {})
        user = MeshNode.User()
        user.id = user_data.get('id', '')
        user.long_name = user_data.get('longName', '')
        user.short_name = user_data.get('shortName', '')
        user.macaddr = user_data.get('macaddr', '')
        user.hw_model = user_data.get('hwModel', '')
        user.public_key = user_data.get('publicKey', '')

        position_data = node_data.get('position', {})
        position = MeshNode.Position(logged_time=datetime.now(timezone.utc))
        position.latitude = position_data.get('latitude', 0.0)
        position.longitude = position_data.get('longitude', 0.0)
        position.altitude = position_data.get('altitude', 0)
        # 'time' is a timestamp int
        position.reported_time = datetime.fromtimestamp(position_data.get('time'), timezone.utc) \
            if 'time' in position_data else datetime.now(timezone.utc)
        position.location_source = position_data.get('locationSource', '')

        device_metrics_data = node_data.get('deviceMetrics', {})
        device_metrics = MeshNode.DeviceMetrics(logged_time=datetime.now(timezone.utc))
        device_metrics.battery_level = device_metrics_data.get('batteryLevel', 0)
        device_metrics.voltage = device_metrics_data.get('voltage', 0.0)
        device_metrics.channel_utilization = device_metrics_data.get('channelUtilization', 0.0)
        device_metrics.air_util_tx = device_metrics_data.get('airUtilTx', 0.0)
        device_metrics.uptime_seconds = device_metrics_data.get('uptimeSeconds', 0)

        node = MeshNode()
        node.user = user
        node.position = position
        node.device_metrics = device_metrics
        node.is_favorite = node_data.get('isFavorite', False)

        return node
