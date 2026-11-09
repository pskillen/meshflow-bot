"""build_radio hands the serializer the radio's live firmware version."""

import unittest
from unittest.mock import MagicMock, patch

from src import main


class TestBuildRadioFirmwareWiring(unittest.TestCase):
    def test_serializer_reads_firmware_from_the_radio(self):
        radio = MagicMock()
        radio.firmware_version = None
        with (
            patch.object(main, "RADIO_PROTOCOL", "meshtastic"),
            patch.object(main, "MESHTASTIC_IP", "127.0.0.1"),
            patch.object(main, "MeshtasticRadio", return_value=radio),
        ):
            _, serializer = main.build_radio(MagicMock())
        self.assertIsNone(serializer._firmware_version())
        radio.firmware_version = "2.8.2.d5f1619"
        self.assertEqual(serializer._firmware_version(), "2.8.2.d5f1619")


if __name__ == "__main__":
    unittest.main()
