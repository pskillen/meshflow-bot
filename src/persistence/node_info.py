import abc
import json
import logging
import os.path
from datetime import datetime, timezone, timedelta


class AbstractNodeInfoStore(abc.ABC):
    DEFAULT_ONLINE_THRESHOLD = 7200  # 2 hours
    online_threshold_sec: int
    packet_counter_reset_time: datetime

    def __init__(self):
        self.online_threshold_sec = self.DEFAULT_ONLINE_THRESHOLD
        self.packet_counter_reset_time = datetime.now(timezone.utc)

    @abc.abstractmethod
    def node_packet_received(self, node_id: str, packet_type: str) -> None:
        pass

    @abc.abstractmethod
    def update_last_heard(self, node_id: str, last_heard: datetime = None) -> None:
        pass

    @abc.abstractmethod
    def reset_packets_today(self) -> None:
        pass

    @abc.abstractmethod
    def get_online_nodes(self) -> dict[str, datetime]:
        pass

    @abc.abstractmethod
    def get_offline_nodes(self) -> dict[str, datetime]:
        pass

    @abc.abstractmethod
    def get_all_nodes(self) -> dict[str, datetime]:
        pass

    @abc.abstractmethod
    def get_last_heard(self, node_id) -> datetime | None:
        pass

    @abc.abstractmethod
    def get_node_packets_today(self, node_id: str) -> int:
        pass

    @abc.abstractmethod
    def get_node_packets_today_breakdown(self, node_id: str) -> dict[str, int]:
        pass

    @abc.abstractmethod
    def get_all_nodes_packets_today(self) -> dict[str, int]:
        pass

    @abc.abstractmethod
    def get_all_nodes_packets_today_breakdown(self) -> dict[str, dict[str, int]]:
        pass


class InMemoryNodeInfoStore(AbstractNodeInfoStore):
    # node_id -> last_heard
    nodes_last_heard: dict[str, datetime]

    # node_id -> packet_count
    node_packets_today: dict[str, int]

    # node_id -> packet_type -> packet_count
    node_packets_today_breakdown: dict[str, dict[str, int]]

    def __init__(self):
        super().__init__()
        self.nodes_last_heard = {}
        self.node_packets_today = {}
        self.node_packets_today_breakdown = {}

    def node_packet_received(self, node_id: str, packet_type: str) -> None:
        self.update_last_heard(node_id)

        if node_id not in self.node_packets_today:
            self.node_packets_today[node_id] = 1
        else:
            self.node_packets_today[node_id] += 1

        if node_id not in self.node_packets_today_breakdown:
            self.node_packets_today_breakdown[node_id] = {}

        if packet_type not in self.node_packets_today_breakdown[node_id]:
            self.node_packets_today_breakdown[node_id][packet_type] = 1
        else:
            self.node_packets_today_breakdown[node_id][packet_type] += 1

    def update_last_heard(self, node_id: str, last_heard: datetime = None) -> None:
        self.nodes_last_heard[node_id] = last_heard if last_heard else datetime.now(timezone.utc)

    def reset_packets_today(self) -> None:
        self.node_packets_today = {}
        self.node_packets_today_breakdown = {}

    def get_online_nodes(self) -> dict[str, datetime]:
        return {node_id: last_heard for node_id, last_heard in self.nodes_last_heard.items()
                if last_heard and last_heard > datetime.now(timezone.utc) - timedelta(seconds=self.online_threshold_sec)}

    def get_offline_nodes(self) -> dict[str, datetime]:
        return {node_id: last_heard for node_id, last_heard in self.nodes_last_heard.items()
                if not last_heard or last_heard <= datetime.now(timezone.utc) - timedelta(seconds=self.online_threshold_sec)}

    def get_all_nodes(self) -> dict[str, datetime]:
        return self.nodes_last_heard

    def load_from_file(self, node_info_file: str) -> None:
        if not os.path.exists(node_info_file):
            return

        with open(node_info_file, 'r') as file:
            data = json.load(file)
            self.nodes_last_heard = {k: (datetime.fromisoformat(v) if v else None) for k, v in data['nodes_last_heard'].items()}
            self.node_packets_today = data['node_packets_today']
            self.node_packets_today_breakdown = data['node_packets_today_breakdown']

    def persist_to_file(self, node_info_file: str) -> None:
        with open(node_info_file, 'w') as file:
            data = {
                'nodes_last_heard': {k: v.isoformat() for k, v in self.nodes_last_heard.items()},
                'node_packets_today': self.node_packets_today,
                'node_packets_today_breakdown': self.node_packets_today_breakdown
            }
            json.dump(data, file, indent=4)
        logging.info(f"Node info persisted to {node_info_file}")

    def get_last_heard(self, node_id) -> datetime | None:
        return self.nodes_last_heard.get(node_id)

    def get_node_packets_today(self, node_id: str) -> int:
        return self.node_packets_today.get(node_id, 0)

    def get_node_packets_today_breakdown(self, node_id: str) -> dict[str, int]:
        return self.node_packets_today_breakdown.get(node_id, {})

    def get_all_nodes_packets_today(self) -> dict[str, int]:
        return self.node_packets_today

    def get_all_nodes_packets_today_breakdown(self) -> dict[str, dict[str, int]]:
        return self.node_packets_today_breakdown
