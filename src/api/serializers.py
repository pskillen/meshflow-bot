import datetime
from abc import ABC

from src.data_classes import MeshNode


class AbstractModelSerializer(ABC):
    @classmethod
    def to_api_dict(cls, model) -> dict:
        raise NotImplementedError

    @classmethod
    def from_api_dict(cls, model_data: dict):
        raise NotImplementedError

    @staticmethod
    def date_to_api(date: datetime.datetime) -> str:
        return date.strftime("%Y-%m-%d %H:%M:%SZ")

    @staticmethod
    def date_from_api(date_str: str) -> datetime.datetime:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%SZ")


class PositionSerializer(AbstractModelSerializer):
    @classmethod
    def to_api_dict(cls, position: MeshNode.Position) -> dict:
        return {
            "logged_time": cls.date_to_api(position.logged_time),  # api v1 compatibility
            "loggedTime": cls.date_to_api(position.logged_time),
            "reported_time": cls.date_to_api(position.reported_time),  # api v2 compatibility
            "reportedTime": cls.date_to_api(position.reported_time),
            "latitude": position.latitude,
            "longitude": position.longitude,
            "altitude": position.altitude,
            "location_source": position.location_source or "LOC_UNKNOWN",
            "locationSource": position.location_source or "LOC_UNKNOWN",
        }

    @classmethod
    def from_api_dict(cls, position_data: dict) -> MeshNode.Position:
        return MeshNode.Position(
            logged_time=cls.date_from_api(position_data.get('logged_time') or position_data.get('loggedTime')),
            reported_time=cls.date_from_api(position_data.get('reported_time') or position_data.get('reportedTime')),
            latitude=position_data['latitude'],
            longitude=position_data['longitude'],
            altitude=position_data['altitude'],
            location_source=position_data.get('location_source') or position_data.get('locationSource')
        )


class DeviceMetricsSerializer(AbstractModelSerializer):
    @classmethod
    def to_api_dict(cls, device_metrics: MeshNode.DeviceMetrics) -> dict:
        return {
            "logged_time": cls.date_to_api(device_metrics.logged_time),  # api v1 compatibility
            "loggedTime": cls.date_to_api(device_metrics.logged_time),
            "reported_time": cls.date_to_api(device_metrics.logged_time),  # api v2 compatibility
            "reportedTime": cls.date_to_api(device_metrics.logged_time),
            "battery_level": device_metrics.battery_level,
            "batteryLevel": device_metrics.battery_level,
            "voltage": device_metrics.voltage,
            "channel_utilization": device_metrics.channel_utilization,
            "channelUtilization": device_metrics.channel_utilization,
            "air_util_tx": device_metrics.air_util_tx,
            "airUtilTx": device_metrics.air_util_tx,
            "uptime_seconds": device_metrics.uptime_seconds,
            "uptimeSeconds": device_metrics.uptime_seconds
        }

    @classmethod
    def from_api_dict(cls, device_metrics_data: dict) -> MeshNode.DeviceMetrics:
        return MeshNode.DeviceMetrics(
            logged_time=cls.date_from_api(device_metrics_data.get('logged_time') or device_metrics_data.get('loggedTime') or device_metrics_data.get('reported_time') or device_metrics_data.get('reportedTime')),
            battery_level=device_metrics_data.get('battery_level') or device_metrics_data.get('batteryLevel'),
            voltage=device_metrics_data['voltage'],
            channel_utilization=device_metrics_data.get('channel_utilization') or device_metrics_data.get('channelUtilization'),
            air_util_tx=device_metrics_data.get('air_util_tx') or device_metrics_data.get('airUtilTx'),
            uptime_seconds=device_metrics_data.get('uptime_seconds') or device_metrics_data.get('uptimeSeconds')
        )


class MeshNodeSerializer(AbstractModelSerializer):
    # BE CAREFUL: The API node/user models do not match the local node/user models (same fields, moved around)

    @classmethod
    def to_api_dict(cls, node: MeshNode) -> dict:
        node_data = {
            "id": node.user.id,
            "macaddr": node.user.macaddr,
            "hw_model": node.user.hw_model,
            "hwModel": node.user.hw_model,
            "public_key": node.user.public_key,
            "publicKey": node.user.public_key,
            'user': {
                "long_name": node.user.long_name,
                "longName": node.user.long_name,
                "short_name": node.user.short_name,
                "shortName": node.user.short_name
            }
        }

        # only log a position if it's actually set
        if node.position and not \
                (node.position.latitude == 0 and node.position.longitude == 0 and node.position.altitude == 0):
            node_data['position'] = PositionSerializer.to_api_dict(node.position)

        if node.device_metrics:
            node_data['device_metrics'] = DeviceMetricsSerializer.to_api_dict(node.device_metrics)
            node_data['deviceMetrics'] = DeviceMetricsSerializer.to_api_dict(node.device_metrics)

        return node_data

    @classmethod
    def from_api_dict(cls, node_data: dict) -> MeshNode:
        user_data = node_data['user']
        user = MeshNode.User(
            node_id=node_data['id'],
            macaddr=node_data['macaddr'],
            hw_model=node_data.get('hw_model') or node_data.get('hwModel'),
            public_key=node_data.get('public_key') or node_data.get('publicKey'),
            long_name=user_data.get('long_name') or user_data.get('longName'),
            short_name=user_data.get('short_name') or user_data.get('shortName')
        )

        position_data = node_data.get('position')
        position = None
        if position_data:
            position = PositionSerializer.from_api_dict(position_data)

        device_metrics_data = node_data.get('device_metrics') or node_data.get('deviceMetrics')
        device_metrics = None
        if device_metrics_data:
            device_metrics = DeviceMetricsSerializer.from_api_dict(device_metrics_data)

        node = MeshNode()
        node.user = user
        node.position = position
        node.device_metrics = device_metrics

        return node
