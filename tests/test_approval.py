import unittest

from genieagent.models import APPROVAL_APPROVED, APPROVAL_PENDING
from genieagent.outreach.drafts import (
    already_contacted,
    approval_gate,
    plan_follow_up,
    prepare_drafts,
)
from genieagent.util import now_iso
from tests.helpers import temp_config


def base_lead(**overrides):
    lead = {
        "lead_id": "lead-1",
        "company_name": "Acme Inc",
        "email": "info@acme.com",
        "email_status": "valid",
        "email_verified_at": "2026-01-01T00:00:00Z",
        "qualification_status": "qualified",
        "qualification_score": "88",
        "do_not_contact": "false",
        "outreach_status": "not_contacted",
        "phone_business": "15551234567",
        "phone_type": "business",
        "consent_basis": "",
        "notes": "We need a new website for our business and have a budget.",
        "source_url": "https://acme.com/project",
        "company_name": "Acme Inc",
        "domain": "acme.com",
        "website": "https://acme.com",
        "email_source": "hunter_email_verifier",
        "service_fit": "Website / web application development",
        "verification_status": "verified_genuine",
        "identity_status": "matched",
        "verification_checked_at": now_iso(),
        "verified_at": now_iso(),
        "verification_fingerprint": "",
        "fraud_indicators": "",
        "legal_basis": "legitimate_interest_b2b",
    }
    lead.update(overrides)
    return lead


def approved_draft(**overrides):
    draft = {
        "draft_id": "draft-1",
        "lead_id": "lead-1",
        "channel": "email",
        "provider": "brevo_smtp",
        "recipient": "info@acme.com",
        "subject": "Website project for Acme",
        "body": (
            "Hello,\n\nI noticed your published requirement for a new business website. "
            "I build responsive sites and can share a short plan if the project is still open. "
            "Examples: https://portfolio.example.com/\n\nIf this is already handled, no reply is needed.\n\nKind regards,\nTest Owner"
        ),
        "approval_status": APPROVAL_APPROVED,
        "approved_by": "owner@example.com",
        "approved_at": "2026-01-02T00:00:00Z",
        "sent_at": "",
        "created_at": "2026-01-02T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    draft.update(overrides)
    return draft


class ApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.config = temp_config(outreach_send_enabled=True)

    def test_requires_approved_status(self):
        draft = approved_draft(approval_status=APPROVAL_PENDING)
        ok, reason = approval_gate(draft, base_lead(), self.config, [draft])
        self.assertFalse(ok)
        self.assertIn("not 'approved'", reason)

    def test_requires_sending_enabled(self):
        ok, reason = approval_gate(approved_draft(), base_lead(), temp_config(outreach_send_enabled=False), [])
        self.assertFalse(ok)
        self.assertIn("OUTREACH_SEND_ENABLED", reason)

    def test_requires_owner_approver(self):
        draft = approved_draft(approved_by="someone@else.com")
        ok, reason = approval_gate(draft, base_lead(), self.config, [draft])
        self.assertFalse(ok)
        self.assertIn("owner", reason.lower())

    def test_requires_verified_email(self):
        ok, reason = approval_gate(approved_draft(), base_lead(email_status="accept_all"), self.config, [])
        self.assertFalse(ok)
        self.assertIn("verified", reason)

    def test_requires_qualification(self):
        ok, reason = approval_gate(approved_draft(), base_lead(qualification_status="pending"), self.config, [])
        self.assertFalse(ok)
        self.assertIn("qualified", reason)

    def test_rejects_low_score(self):
        ok, reason = approval_gate(approved_draft(), base_lead(qualification_score="40"), self.config, [])
        self.assertFalse(ok)
        self.assertIn("OUTREACH_MIN_SCORE", reason)

    def test_rejects_opt_out(self):
        ok, reason = approval_gate(approved_draft(), base_lead(outreach_status="opted_out"), self.config, [])
        self.assertFalse(ok)

    def test_rejects_suppressed_recipient(self):
        config = temp_config(outreach_send_enabled=True, suppressed_emails=("info@acme.com",))
        ok, reason = approval_gate(approved_draft(), base_lead(), config, [])
        self.assertFalse(ok)
        self.assertIn("suppression", reason)

    def test_rejects_recipient_mismatch(self):
        draft = approved_draft(recipient="other@acme.com")
        ok, reason = approval_gate(draft, base_lead(), self.config, [draft])
        self.assertFalse(ok)
        self.assertIn("does not match", reason)

    def test_rejects_duplicate_send(self):
        previous = approved_draft(draft_id="draft-0", sent_at="2026-01-03T00:00:00Z", approval_status="sent")
        ok, reason = approval_gate(approved_draft(), base_lead(), self.config, [previous])
        self.assertFalse(ok)
        self.assertIn("already sent", reason)

    def test_rejects_placeholder_body(self):
        draft = approved_draft(body="Hi {{first_name}}, I build {{service}}. Portfolio: https://portfolio.example.com/")
        ok, reason = approval_gate(draft, base_lead(), self.config, [draft])
        self.assertFalse(ok)
        self.assertIn("validation failed", reason.lower())

    def test_passes_when_everything_is_valid(self):
        draft = approved_draft()
        ok, reason = approval_gate(draft, base_lead(), self.config, [draft])
        self.assertTrue(ok, reason)

    def test_blocks_lead_without_strict_verification(self):
        draft = approved_draft()
        for status in ("", "pending_verification", "rejected_fraud"):
            ok, reason = approval_gate(draft, base_lead(verification_status=status), self.config, [draft])
            self.assertFalse(ok, status)
            self.assertIn("verified", reason.lower())

    def test_blocks_stale_verification(self):
        lead = base_lead(verification_checked_at="2020-01-01T00:00:00Z")
        ok, reason = approval_gate(approved_draft(), lead, self.config, [])
        self.assertFalse(ok)
        self.assertIn("pipeline_verify", reason)

    def test_unattended_requires_auto_flag(self):
        ok, reason = approval_gate(approved_draft(), base_lead(), self.config, [], unattended=True)
        self.assertFalse(ok)
        self.assertIn("AUTO_OUTREACH_ENABLED", reason)

    def test_whatsapp_requires_consent_and_send_flag(self):
        config = temp_config(outreach_send_enabled=True, whatsapp_provider="green_api", whatsapp_send_enabled=True, green_api_id_instance="1", green_api_token="t")
        draft = approved_draft(channel="whatsapp", provider="green_api", recipient="15551234567")
        ok, reason = approval_gate(draft, base_lead(), config, [])
        self.assertFalse(ok)
        self.assertIn("consent", reason.lower())
        ok, reason = approval_gate(draft, base_lead(consent_basis="Owner recorded inbound WhatsApp enquiry"), config, [])
        self.assertTrue(ok, reason)

    def test_whatsapp_disabled_by_default(self):
        draft = approved_draft(channel="whatsapp", recipient="15551234567")
        ok, reason = approval_gate(draft, base_lead(consent_basis="x"), self.config, [])
        self.assertFalse(ok)
        self.assertIn("WHATSAPP_SEND_ENABLED", reason)


class PrepareDraftsTests(unittest.TestCase):
    def test_drafts_are_never_approved_automatically(self):
        config = temp_config()
        generated = {
            "subject": "Website project",
            "email_body": "Hello, I saw your website project and would like to share a short plan. "
            "Portfolio: https://portfolio.example.com/\n\nKind regards,\nTest Owner",
            "whatsapp_body": "",
        }
        drafts, reasons = prepare_drafts(base_lead(), generated, config, [], include_whatsapp=False)
        self.assertEqual(reasons, [])
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["approval_status"], APPROVAL_PENDING)
        self.assertEqual(drafts[0]["approved_by"], "")

    def test_no_draft_for_unverified_email(self):
        drafts, reasons = prepare_drafts(
            base_lead(email_status="unverified"),
            {"subject": "S", "email_body": "Body long enough to look like a real message. Portfolio: https://portfolio.example.com/"},
            temp_config(),
            [],
        )
        self.assertEqual(drafts, [])
        self.assertTrue(any("verification" in reason.lower() for reason in reasons), reasons)

    def test_no_duplicate_pending_draft(self):
        existing = [approved_draft(approval_status=APPROVAL_PENDING)]
        drafts, reasons = prepare_drafts(
            base_lead(),
            {"subject": "S", "email_body": "Body long enough to look like a real message. Portfolio: https://portfolio.example.com/"},
            temp_config(),
            existing,
        )
        self.assertEqual(drafts, [])
        self.assertTrue(reasons)

    def test_whatsapp_draft_requires_business_number_and_consent(self):
        config = temp_config(whatsapp_provider="green_api", green_api_id_instance="1", green_api_token="t")
        drafts, reasons = prepare_drafts(
            base_lead(),
            {"subject": "S", "email_body": "Body long enough to look like a real message. Portfolio: https://portfolio.example.com/", "whatsapp_body": "Hi"},
            config,
            [],
        )
        self.assertEqual(len(drafts), 1)
        self.assertTrue(any("consent" in reason.lower() for reason in reasons))


class FollowUpTests(unittest.TestCase):
    def test_follow_up_not_due_immediately(self):
        drafts = [approved_draft(approval_status="sent", sent_at=now_iso())]
        due, previous, reason = plan_follow_up(base_lead(), drafts, temp_config())
        self.assertFalse(due)
        self.assertIn("not due", reason)

    def test_follow_up_due_after_threshold(self):
        drafts = [approved_draft(approval_status="sent", sent_at="2020-01-01T00:00:00Z")]
        due, previous, reason = plan_follow_up(base_lead(), drafts, temp_config())
        self.assertTrue(due, reason)
        self.assertEqual(previous, "draft-1")

    def test_no_follow_up_after_reply(self):
        drafts = [approved_draft(approval_status="sent", sent_at="2020-01-01T00:00:00Z")]
        due, _, reason = plan_follow_up(base_lead(last_reply_at="2020-01-02T00:00:00Z"), drafts, temp_config())
        self.assertFalse(due)
        self.assertIn("replied", reason)

    def test_follow_ups_are_capped(self):
        drafts = [approved_draft(approval_status="sent", sent_at="2020-01-01T00:00:00Z")]
        for index in range(3):
            drafts.append(
                approved_draft(
                    draft_id=f"f{index}",
                    follow_up_of="draft-1",
                    approval_status="sent",
                    sent_at=f"2020-02-0{index + 1}T00:00:00Z",
                )
            )
        due, _, reason = plan_follow_up(base_lead(), drafts, temp_config())
        self.assertFalse(due)
        self.assertIn("All follow-ups", reason)

    def test_already_contacted_helper(self):
        self.assertTrue(already_contacted([approved_draft(approval_status="sent")], "lead-1", "email"))
        self.assertFalse(already_contacted([approved_draft(approval_status=APPROVAL_PENDING)], "lead-1", "email"))


if __name__ == "__main__":
    unittest.main()
