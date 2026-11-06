import unittest
from pathlib import Path

from genieagent.config import Config, ConfigError, ensure_supported_model, load_env_file


class ConfigDefaultsTests(unittest.TestCase):
    def test_automatic_outreach_is_off_by_default(self):
        config = Config.from_env(env={}, dotenv_path=None)
        self.assertFalse(config.outreach_send_enabled)
        self.assertFalse(config.auto_outreach_enabled)
        self.assertFalse(config.whatsapp_send_enabled)
        self.assertEqual(config.whatsapp_provider, "none")
        self.assertEqual(config.gemini_model, "gemini-3.8-flash")
        self.assertFalse(config.safety_summary()["automatic_outreach"])

    def test_boolean_flags_are_strict(self):
        with self.assertRaises(ConfigError):
            Config.from_env(env={"OUTREACH_SEND_ENABLED": "maybe"}, dotenv_path=None)
        self.assertFalse(Config.from_env(env={"OUTREACH_SEND_ENABLED": "false"}, dotenv_path=None).outreach_send_enabled)
        self.assertTrue(Config.from_env(env={"OUTREACH_SEND_ENABLED": "true"}, dotenv_path=None).outreach_send_enabled)

    def test_whatsapp_provider_aliases(self):
        self.assertEqual(Config.from_env(env={"WHATSAPP_PROVIDER": "meta"}, dotenv_path=None).whatsapp_provider, "meta_cloud")
        self.assertEqual(Config.from_env(env={"WHATSAPP_PROVIDER": "green"}, dotenv_path=None).whatsapp_provider, "green_api")
        self.assertEqual(Config.from_env(env={"WHATSAPP_PROVIDER": "off"}, dotenv_path=None).whatsapp_provider, "none")
        with self.assertRaises(ConfigError):
            Config.from_env(env={"WHATSAPP_PROVIDER": "telegram"}, dotenv_path=None)

    def test_sheets_auth_modes(self):
        oauth = Config.from_env(
            env={
                "GOOGLE_SHEETS_ID": "sheet-id",
                "GOOGLE_OAUTH_CLIENT_ID": "client",
                "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
                "GOOGLE_OAUTH_REFRESH_TOKEN": "refresh",
            },
            dotenv_path=None,
        )
        self.assertEqual(oauth.sheets_auth_mode, "oauth_refresh_token")
        self.assertTrue(oauth.sheets_ready)
        self.assertEqual(Config.from_env(env={}, dotenv_path=None).sheets_auth_mode, "none")

    def test_retired_gemini_model_rejected(self):
        with self.assertRaises(ConfigError):
            ensure_supported_model("gemini-1.5-flash")
        with self.assertRaises(ConfigError):
            ensure_supported_model("")
        self.assertEqual(ensure_supported_model("gemini-3.8-flash"), "gemini-3.8-flash")

    def test_secret_redaction_list(self):
        config = Config.from_env(env={"APOLLO_API_KEY": "apollo-secret", "GEMINI_API_KEY": "gemini-secret"}, dotenv_path=None)
        self.assertIn("apollo-secret", config.secrets())
        self.assertNotIn("apollo-secret", str(config.safety_summary()))

    def test_env_file_parsing(self):
        path = Path(self.id().replace(".", "-") + ".env")
        path.write_text('APOLLO_API_KEY="quoted-value"\n# comment\nBAD LINE\nGEMINI_MODEL=gemini-3.8-flash\n', encoding="utf-8")
        try:
            env = load_env_file(path, env={})
        finally:
            path.unlink()
        self.assertEqual(env["APOLLO_API_KEY"], "quoted-value")
        self.assertEqual(env["GEMINI_MODEL"], "gemini-3.8-flash")
        self.assertNotIn("BAD LINE", env)


if __name__ == "__main__":
    unittest.main()
