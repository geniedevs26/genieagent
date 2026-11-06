import json
import unittest

from genieagent.config import ConfigError
from genieagent.outreach.whatsapp import (
    GreenAPIProvider,
    MetaCloudProvider,
    normalize_phone,
    provider_status,
)
from tests.helpers import temp_config


def fake_transport(status=200, payload=None, captured=None):
    def _send(method, url, headers, body):
        if captured is not None:
            captured.append({"method": method, "url": url, "headers": headers, "body": body})
        return status, {}, json.dumps(payload or {"messages": [{"id": "wamid.TEST"}]})

    return _send


class PhoneTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_phone("+1 (555) 123-4567"), "15551234567")
        self.assertEqual(normalize_phone("0044 20 7946 0000"), "442079460000")
        self.assertEqual(normalize_phone(""), "")


class MetaProviderTests(unittest.TestCase):
    def test_requires_credentials(self):
        with self.assertRaises(ConfigError):
            MetaCloudProvider("", "token")

    def test_blocks_freeform_first_contact_without_template(self):
        provider = MetaCloudProvider("123", "token", transport=fake_transport())
        result = provider.send_text("+15551234567", "Hello")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("template", result.detail.lower())
        self.assertFalse(provider.can_start_conversation)

    def test_sends_approved_template(self):
        captured = []
        provider = MetaCloudProvider(
            "123", "token", template_name="initial_outreach", template_lang="en_US", transport=fake_transport(captured=captured)
        )
        result = provider.send_text("+15551234567", "Hello there")
        self.assertTrue(result.ok)
        self.assertEqual(result.mode, "template")
        payload = json.loads(captured[0]["body"].decode("utf-8"))
        self.assertEqual(payload["to"], "15551234567")
        self.assertEqual(payload["template"]["name"], "initial_outreach")
        self.assertEqual(payload["template"]["language"]["code"], "en_US")
        self.assertEqual(payload["messaging_product"], "whatsapp")
        self.assertEqual(captured[0]["headers"]["Authorization"], "Bearer token")

    def test_reports_meta_errors(self):
        provider = MetaCloudProvider(
            "123", "token", template_name="t", transport=fake_transport(400, {"error": {"message": "Invalid parameter"}})
        )
        result = provider.send_text("+15551234567", "Hello")
        self.assertFalse(result.ok)
        self.assertIn("Invalid parameter", result.detail)


class GreenProviderTests(unittest.TestCase):
    def test_requires_credentials(self):
        with self.assertRaises(ConfigError):
            GreenAPIProvider("", "token")

    def test_sends_text_with_chat_id(self):
        captured = []
        provider = GreenAPIProvider("999", "secret-token", transport=fake_transport(200, {"idMessage": "abc123"}, captured))
        result = provider.send_text("+1 555 123 4567", "Hello from GenieAgent")
        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, "abc123")
        self.assertIn("/waInstance999/sendMessage/secret-token", captured[0]["url"])
        payload = json.loads(captured[0]["body"].decode("utf-8"))
        self.assertEqual(payload["chatId"], "15551234567@c.us")


class ProviderStatusTests(unittest.TestCase):
    def test_status_without_provider(self):
        status = provider_status(temp_config())
        self.assertFalse(status["configured"])
        self.assertEqual(status["provider"], "none")

    def test_status_warns_meta_template(self):
        config = temp_config(
            whatsapp_provider="meta_cloud",
            whatsapp_meta_phone_number_id="123",
            whatsapp_meta_token="token",
        )
        status = provider_status(config)
        self.assertTrue(status["configured"])
        self.assertIn("template", status["note"].lower())


if __name__ == "__main__":
    unittest.main()
