import json
import unittest

from genieagent.models import APPROVAL_PENDING
from genieagent.pipeline import build_dashboard, redact_pii
from genieagent.storage.csv_store import activity_table, leads_table, outreach_table
from genieagent.util import mask_email, mask_phone
from tests.helpers import temp_config


class MaskingTests(unittest.TestCase):
    def test_mask_email_keeps_domain_only(self):
        self.assertEqual(mask_email("john.smith@acme.com"), "j******@acme.com")
        self.assertEqual(mask_email("jane.doe@acme.com"), "j******@acme.com")
        self.assertEqual(mask_email(""), "")

    def test_mask_phone_keeps_last_two_digits(self):
        self.assertEqual(mask_phone("+15551234567"), "*********67")

    def test_redact_pii_removes_emails_and_numbers(self):
        text = "Contact jane@acme.com or +1 555 123 4567 with key sk-abcdefghijklmnop"
        redacted = redact_pii(text)
        self.assertNotIn("jane@acme.com", redacted)
        self.assertNotIn("5551234567", redacted.replace(" ", ""))
        self.assertNotIn("sk-abcdefghijklmnop", redacted)


class DashboardTests(unittest.TestCase):
    def test_dashboard_excludes_contact_details(self):
        config = temp_config()
        leads_table(config.leads_csv).upsert(
            [
                {
                    "lead_id": "lead-1",
                    "company_name": "Acme Inc",
                    "domain": "acme.com",
                    "email": "jane.doe@acme.com",
                    "email_status": "valid",
                    "email_verified_at": "2026-01-01T00:00:00Z",
                    "phone_business": "15551234567",
                    "phone_type": "business",
                    "qualification_status": "qualified",
                    "qualification_score": "88",
                    "outreach_status": "sent",
                    "source_provider": "apollo",
                    "source_url": "https://acme.com/project",
                    "notes": "Needs a website for the retail business.",
                    "order_status": "interested",
                }
            ]
        )
        outreach_table(config.outreach_csv).upsert(
            [
                {
                    "draft_id": "draft-1",
                    "lead_id": "lead-1",
                    "channel": "email",
                    "provider": "brevo_smtp",
                    "recipient": "jane.doe@acme.com",
                    "recipient_masked": "j*******@acme.com",
                    "subject": "Website project",
                    "body": "Secret body with jane.doe@acme.com",
                    "approval_status": APPROVAL_PENDING,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
        )
        activity_table(config.activity_csv).upsert(
            [{"event_id": "e1", "timestamp": "2026-01-01T00:00:00Z", "event_type": "test", "status": "ok", "summary": "Contact jane.doe@acme.com", "details": "", "lead_id": "lead-1"}],
            touch=False,
        )
        payload = build_dashboard(config)
        serialized = json.dumps(payload)
        self.assertNotIn("jane.doe@acme.com", serialized)
        self.assertNotIn("15551234567", serialized)
        self.assertNotIn("Secret body", serialized)
        self.assertEqual(payload["totals"]["leads"], 1)
        self.assertEqual(payload["totals"]["qualified"], 1)
        self.assertEqual(payload["totals"]["drafts_pending_approval"], 1)
        self.assertEqual(payload["totals"]["orders"], 1)
        self.assertEqual(payload["leads"][0]["email_masked"], "j******@acme.com")
        self.assertFalse(payload["safety"]["automatic_outreach"])
        self.assertFalse(payload["safety"]["outreach_send_enabled"])

    def test_empty_dashboard(self):
        config = temp_config()
        payload = build_dashboard(config)
        self.assertEqual(payload["totals"]["leads"], 0)
        self.assertEqual(payload["leads"], [])


if __name__ == "__main__":
    unittest.main()
