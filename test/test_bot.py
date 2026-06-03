import unittest
from test.fake_radio import FakeRadio
from unittest.mock import MagicMock, patch

from src.bot import MeshflowBot
from src.radio.events import ConnectionEstablished


class TestMeshflowBot(unittest.TestCase):
    def setUp(self):
        self.fake_radio = FakeRadio(local_node_id="!aabbccdd", local_nodenum=0xAABBCCDD)
        self.bot = MeshflowBot(radio=self.fake_radio)

    def test_connect_delegates_to_radio(self):
        self.bot.connect()
        self.fake_radio.connect.assert_called_once()

    def test_disconnect_delegates_to_radio(self):
        self.bot.disconnect()
        self.fake_radio.disconnect.assert_called_once()

    def test_my_id_proxies_radio(self):
        self.assertEqual(self.bot.my_id, "!aabbccdd")
        self.assertEqual(self.bot.my_nodenum, 0xAABBCCDD)

    def test_traceroute_skipped_when_disconnected(self):
        self.bot.on_traceroute_command(0x12345678)
        self.fake_radio.send_traceroute.assert_not_called()

    def test_traceroute_forwarded_when_connected(self):
        self.fake_radio._is_connected = True
        self.bot.on_traceroute_command(0x12345678)
        self.fake_radio.send_traceroute.assert_called_once_with(0x12345678)

    def test_apply_mc_channel_config_ignored_without_run_coroutine(self):
        self.bot.on_apply_mc_channel_config([{"mc_channel_idx": 0, "name": "x"}])

    def test_apply_mc_channel_config_syncs_after_apply(self):
        mc_radio = MagicMock()
        mc_radio.run_coroutine = MagicMock()
        bot = MeshflowBot(radio=mc_radio)
        bot.storage_apis = [MagicMock(), MagicMock()]
        channels = [{"mc_channel_idx": 0, "name": "Public"}]
        mc_radio.schedule_channel_sync = MagicMock()
        with patch(
            "src.meshcore.channel_sync.apply_channels_on_device", return_value=True
        ) as apply_mock:
            bot.on_apply_mc_channel_config(channels)
        apply_mock.assert_called_once_with(mc_radio, channels)
        mc_radio.schedule_channel_sync.assert_called_once_with(
            bot.storage_apis,
            scope_hints=channels,
        )

    def test_meshcore_connection_schedules_channel_sync(self):
        mc_radio = MagicMock()
        mc_radio.schedule_channel_sync = MagicMock()
        bot = MeshflowBot(radio=mc_radio)
        bot.storage_apis = [MagicMock()]
        bot.print_nodes = MagicMock()
        bot.ws_client = None
        bot._on_connection_established(
            ConnectionEstablished(
                local_node_id="mc:abc",
                local_nodenum=0,
                extras={"meshcore": True},
            )
        )
        mc_radio.schedule_channel_sync.assert_called_once_with(bot.storage_apis)


if __name__ == "__main__":
    unittest.main()
