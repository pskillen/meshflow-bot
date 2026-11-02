"""MeshtasticRadio identity refresh and node-number change handling."""

from src.meshtastic.radio import MeshtasticRadio
from src.radio.events import IdentityChanged
from src.radio.interface import RadioHandlers
from test.meshtastic.fake_interface import FakeInterface


def make_radio(iface: FakeInterface):
    radio = MeshtasticRadio("127.0.0.1")
    events: list = []
    connected: list = []
    radio.set_handlers(
        RadioHandlers(
            on_identity_changed=events.append,
            on_connection_established=connected.append,
        )
    )
    radio._interface = iface
    radio._on_connection_established(iface)
    radio._stop_identity_timer()
    return radio, events, connected


def test_connect_reads_identity():
    radio, events, connected = make_radio(FakeInterface(0x11223344))
    assert radio.local_nodenum == 0x11223344
    assert radio.identity.node_num == 0x11223344
    assert radio.identity.pubkey
    assert radio.identity.region == "EU_868"
    assert radio.firmware_version == "2.7.11.abcdef0"
    assert events == []
    assert len(connected) == 1


def test_no_change_means_no_event():
    radio, events, _ = make_radio(FakeInterface())
    assert radio.check_identity() is False
    assert events == []


def test_node_number_change_refreshes_and_notifies(caplog):
    iface = FakeInterface(0x11223344)
    radio, events, _ = make_radio(iface)
    iface.change_node_num(0x4396524C, new_pubkey_b64="bmV3a2V5")

    with caplog.at_level("WARNING"):
        assert radio.check_identity() is True

    assert radio.local_nodenum == 0x4396524C
    assert radio.local_node_id == "!4396524c"
    assert radio.identity.node_num == 0x4396524C
    assert radio.identity.pubkey == "bmV3a2V5"
    assert events == [IdentityChanged(0x11223344, 0x4396524C)]
    assert events[0].nodenum_changed
    assert any(
        r.levelname == "WARNING" and "node number changed" in r.getMessage()
        for r in caplog.records
    )
    # Stable afterwards
    assert radio.check_identity() is False
    assert len(events) == 1


def test_other_identity_change_notifies_without_number_change():
    iface = FakeInterface(region=0)  # UNSET
    radio, events, _ = make_radio(iface)
    assert radio.identity.region == "UNSET"
    iface.localNode.localConfig.lora.region = 3  # EU_868 set later
    assert radio.check_identity() is True
    assert radio.identity.region == "EU_868"
    assert len(events) == 1
    assert not events[0].nodenum_changed


def test_local_node_updated_event_triggers_check():
    iface = FakeInterface(0x11223344)
    radio, events, _ = make_radio(iface)
    iface.change_node_num(0x4396524C)
    # an update for some other node does not trigger a read
    radio._on_node_updated({"num": 0x99, "user": {}}, iface)
    assert events == []
    # the local node's update does
    radio._on_node_updated({"num": 0x4396524C, "user": {}}, iface)
    assert len(events) == 1
    assert radio.local_nodenum == 0x4396524C


def test_reconnect_with_new_number_notifies():
    iface = FakeInterface(0x11223344)
    radio, events, connected = make_radio(iface)
    new_iface = FakeInterface(0x4396524C)
    radio._interface = new_iface
    radio._on_connection_established(new_iface)
    radio._stop_identity_timer()
    assert events == [IdentityChanged(0x11223344, 0x4396524C)]
    assert len(connected) == 2


def test_check_identity_when_disconnected_does_nothing():
    iface = FakeInterface()
    radio, events, _ = make_radio(iface)
    radio._is_connected = False
    iface.change_node_num(0x4396524C)
    assert radio.check_identity() is False
    assert events == []


def test_identity_timer_is_started_and_stopped():
    iface = FakeInterface()
    radio = MeshtasticRadio("127.0.0.1")
    radio._interface = None
    radio._on_connection_established(iface)
    timer = radio._identity_timer
    assert timer is not None and timer.daemon
    radio.disconnect()
    assert radio._identity_timer is None
    timer.join(1)
    assert not timer.is_alive()


def test_identity_tick_checks_and_reschedules():
    iface = FakeInterface(0x11223344)
    radio, events, _ = make_radio(iface)
    iface.change_node_num(0x4396524C)
    radio._identity_tick()
    assert len(events) == 1
    assert radio._identity_timer is not None
    radio._stop_identity_timer()
