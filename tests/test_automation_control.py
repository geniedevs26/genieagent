import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import automation_control as controls


class ControlTests(unittest.TestCase):
    def test_global_pause_blocks(self):
        with patch.object(controls, "read_rows", return_value=[{"state": "paused"}]):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email")

    def test_emergency_stop_blocks(self):
        with patch.object(controls, "read_rows", return_value=[{"state": "emergency_stopped"}]):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email")

    def test_missing_global_row_blocks(self):
        with patch.object(controls, "read_rows", return_value=[]):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email")

    def test_missing_channel_row_blocks(self):
        with patch.object(controls, "read_rows", side_effect=[
            [{"state": "running"}], []
        ]):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email")

    def test_disabled_channel_blocks(self):
        with patch.object(controls, "read_rows", side_effect=[
            [{"state": "running"}], [{"enabled": False}]
        ]):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email")

    def test_enabled_channel_allows(self):
        with patch.object(controls, "read_rows", side_effect=[
            [{"state": "running"}], [{"enabled": True}]
        ]):
            self.assertTrue(controls.assert_outbound_enabled("key", "owner", "email"))

    def test_api_failure_fails_closed(self):
        with patch.object(controls, "read_rows", side_effect=controls.OutboundBlocked("offline")):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email")

    def test_unknown_channel_blocks(self):
        with self.assertRaises(controls.OutboundBlocked):
            controls.assert_outbound_enabled("key", "owner", "sms")

    def test_suppressed_recipient_blocks(self):
        with patch.object(controls, "read_rows", side_effect=[
            [{"state": "running"}], [{"enabled": True}], [{"id": "suppression"}]
        ]):
            with self.assertRaises(controls.OutboundBlocked):
                controls.assert_outbound_enabled("key", "owner", "email", recipient="person@example.com")

    def test_unsuppressed_recipient_allows(self):
        with patch.object(controls, "read_rows", side_effect=[
            [{"state": "running"}], [{"enabled": True}], []
        ]):
            self.assertTrue(controls.assert_outbound_enabled(
                "key", "owner", "email", recipient="person@example.com"
            ))


if __name__ == "__main__":
    unittest.main()
