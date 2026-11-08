"""The feeder-URL probe runs at connect (before the first upload) and hourly."""

from unittest.mock import MagicMock, patch

import schedule

from src.bot import MeshflowBot
from src.radio.events import ConnectionEstablished
from test.fake_radio import FakeRadio


def make_bot(apis):
    bot = MeshflowBot(radio=FakeRadio(local_node_id="!11223344", local_nodenum=1))
    bot.storage_apis = apis
    bot.print_nodes = MagicMock()
    return bot


def test_probes_every_destination_before_the_bot_version_report():
    calls = []
    apis = [MagicMock(), MagicMock()]
    for index, api in enumerate(apis):
        api.probe_feeder_urls.side_effect = lambda i=index: calls.append(("probe", i))
        api.report_bot_version.side_effect = lambda i=index: calls.append(
            ("report", i)
        )
    bot = make_bot(apis)
    bot._on_connection_established(
        ConnectionEstablished(local_node_id="!11223344", local_nodenum=1)
    )
    assert calls == [("probe", 0), ("probe", 1), ("report", 0), ("report", 1)]


def test_a_failing_destination_does_not_stop_the_others():
    bad, good = MagicMock(), MagicMock()
    bad.probe_feeder_urls.side_effect = RuntimeError("boom")
    bot = make_bot([bad, good])
    bot.probe_feeder_urls()
    good.probe_feeder_urls.assert_called_once()


def test_scheduler_registers_an_hourly_probe_on_a_background_thread():
    schedule.clear()
    try:
        bot = make_bot([MagicMock()])
        bot.node_info = MagicMock()
        with patch("src.bot.time.sleep", side_effect=KeyboardInterrupt):
            bot.start_scheduler()
        hourly = [j for j in schedule.get_jobs() if j.unit == "hours"]
        assert len(hourly) == 1 and hourly[0].interval == 1
        with patch("src.bot.threading.Thread") as thread:
            bot._probe_feeder_urls_in_background()
        thread.return_value.start.assert_called_once()
        assert thread.call_args.kwargs["target"] == bot.probe_feeder_urls
    finally:
        schedule.clear()
