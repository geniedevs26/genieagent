"""Strict verification: three-level decisions, fraud screening and gating."""

import json
import unittest

from genieagent.models import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_SENT,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
    VERIFICATION_VERIFIED,
)
from genieagent.outreach.drafts import approval_gate, prepare_drafts
from genieagent.pipeline import build_dashboard, stage_verify
from genieagent.storage.csv_store import activity_table, leads_table, outreach_table
from genieagent.util import now_iso
from genieagent.verification import (
    apply_verification,
    assess_lead,
    needs_recheck,
    verification_gate,
    verification_summary,
)
from tests.helpers import temp_config


def genuine_lead(**overrides):
    lead = {
        "lead_id": "lead-1",
        "company_name": "Acme Retail",
        "domain": "acme.com",
        "website": "https://acme.com",
        "country": "USA",
        "email": "info@acme.com",
        "email_status": "valid",
        "email_verified_at": "2026-10-01T00:00:00Z",
        "email_source": "hunter_email_verifier",
        "source_provider": "research_pipeline",
        "source_url": "https://acme.com/project",
        "service_fit": "Website / web application development",
        "need_summary": "Direct requirement: we need a new website for our retail business and have a budget of 5000 USD.",
        "notes": "Public buyer requirement on the company's own project page.",
        "do_not_contact": "false",
        "qualification_status": "pending",
        "qualification_score": "0",
        "outreach_status": "not_contacted",
    }
    lead.update(overrides)
    return lead


class AssessmentTests(unittest.TestCase):
    def test_complete_evidence_is_verified_genuine(self):
        assessment = assess_lead(genuine_lead())
        self.assertEqual(assessment["status"], VERIFICATION_VERIFIED)
        self.assertEqual(assessment["identity_status"], "matched")
        self.assertEqual(assessment["fraud_indicators"], [])
        self.assertIn("Verified genuine", assessment["reason"])
        self.assertTrue(assessment["sources"].startswith("website:acme.com|requirement:acme.com"))

    def test_missing_website_holds_the_lead(self):
        assessment = assess_lead(genuine_lead(website="", domain=""))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("No official website", assessment["reason"])

    def test_link_shortener_website_is_rejected(self):
        assessment = assess_lead(genuine_lead(website="https://bit.ly/abc", domain="bit.ly"))
        self.assertEqual(assessment["status"], VERIFICATION_REJECTED)
        self.assertIn("link shortener", assessment["reason"])

    def test_free_host_website_is_only_pending(self):
        assessment = assess_lead(genuine_lead(website="https://acme.wixsite.com/site", domain="acme.wixsite.com"))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("free host", assessment["reason"])

    def test_disposable_email_is_rejected(self):
        assessment = assess_lead(genuine_lead(email="buyer@mailinator.com"))
        self.assertEqual(assessment["status"], VERIFICATION_REJECTED)
        self.assertIn("disposable", assessment["reason"])

    def test_free_mailbox_holds_identity(self):
        assessment = assess_lead(genuine_lead(email="acme.business@gmail.com"))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertEqual(assessment["identity_status"], "unconfirmed")
        self.assertIn("free mailbox", assessment["reason"])

    def test_other_business_domain_holds_identity(self):
        assessment = assess_lead(genuine_lead(email="info@acmegroup.example"))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertEqual(assessment["identity_status"], "unconfirmed")

    def test_missing_email_holds_contact(self):
        assessment = assess_lead(genuine_lead(email="", email_status="", email_verified_at=""))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("No business email", assessment["reason"])

    def test_unverified_email_holds_contact(self):
        assessment = assess_lead(genuine_lead(email_status="accept_all", email_verified_at=""))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("Email status", assessment["reason"])

    def test_apollo_company_record_is_not_a_requirement(self):
        lead = genuine_lead(
            source_provider="apollo",
            notes="Company record from Apollo: company data only, no stated business requirement yet.",
            need_summary="",
        )
        assessment = assess_lead(lead)
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("No source-linked business requirement", assessment["reason"])

    def test_long_company_description_without_source_url_is_not_evidence(self):
        lead = genuine_lead(source_url="", need_summary="We might need a website someday, please contact us about it.")
        assessment = assess_lead(lead)
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("No source-linked business requirement", assessment["reason"])

    def test_missing_service_fit_holds(self):
        assessment = assess_lead(genuine_lead(service_fit=""))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("No matched owner service", assessment["reason"])

    def test_unrelated_service_holds(self):
        assessment = assess_lead(genuine_lead(service_fit="Commercial plumbing and drain cleaning"))
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertIn("does not match a service", assessment["reason"])

    def test_pay_to_work_demand_is_rejected(self):
        lead = genuine_lead(notes="Great project! A registration fee of 50 USD is required before work starts.")
        assessment = assess_lead(lead)
        self.assertEqual(assessment["status"], VERIFICATION_REJECTED)
        self.assertTrue(assessment["fraud_indicators"])
        self.assertIn("registration fee", " ".join(assessment["fraud_indicators"]))

    def test_anonymous_contact_channel_is_quarantined(self):
        lead = genuine_lead(notes="Telegram only, message me there for the project details.")
        assessment = assess_lead(lead)
        self.assertEqual(assessment["status"], VERIFICATION_PENDING)
        self.assertTrue(any("Telegram" in item for item in assessment["fraud_indicators"]))

    def test_checks_are_recorded_for_audit(self):
        assessment = assess_lead(genuine_lead())
        names = {check["check"] for check in assessment["checks"]}
        self.assertEqual(names, {"identity", "fraud_screening", "requirement", "service_match", "contact"})
        self.assertTrue(all(check["result"] == "pass" for check in assessment["checks"]))

    def test_reason_never_contains_the_full_email(self):
        assessment = assess_lead(genuine_lead())
        self.assertNotIn("info@acme.com", json.dumps(assessment))


class ApplyTests(unittest.TestCase):
    def test_apply_writes_every_audit_column(self):
        lead = genuine_lead()
        apply_verification(lead, assess_lead(lead))
        self.assertEqual(lead["verification_status"], VERIFICATION_VERIFIED)
        self.assertEqual(lead["identity_status"], "matched")
        self.assertTrue(lead["verification_sources"])
        self.assertTrue(lead["verified_at"])
        self.assertTrue(lead["verification_checked_at"])
        self.assertTrue(lead["verification_fingerprint"])
        json.loads(lead["verification_checks"])
        self.assertEqual(lead["legal_basis"], "legitimate_interest_b2b")

    def test_apply_clears_verified_at_when_held(self):
        lead = genuine_lead(verified_at="2026-01-01T00:00:00Z")
        apply_verification(lead, assess_lead(genuine_lead(website="")))
        self.assertEqual(lead["verification_status"], VERIFICATION_PENDING)
        self.assertEqual(lead["verified_at"], "")

    def test_changed_record_needs_recheck(self):
        lead = genuine_lead()
        apply_verification(lead, assess_lead(lead))
        self.assertFalse(needs_recheck(lead))
        lead["email"] = "new.person@acme.com"
        self.assertTrue(needs_recheck(lead))

    def test_summary_does_not_count_unassessed_as_verified(self):
        rows = [
            genuine_lead(verification_status=VERIFICATION_VERIFIED),
            genuine_lead(lead_id="lead-2", verification_status=VERIFICATION_PENDING),
            genuine_lead(lead_id="lead-3", verification_status=""),
        ]
        summary = verification_summary(rows)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["verified_genuine"], 1)
        self.assertEqual(summary["unassessed"], 1)
        self.assertEqual(summary["pending_verification"], 1)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.config = temp_config()
        self.lead = genuine_lead()
        apply_verification(self.lead, assess_lead(self.lead, self.config))

    def test_verified_lead_passes(self):
        self.assertEqual(verification_gate(self.lead, self.config), "")

    def test_pending_lead_is_blocked(self):
        self.lead["verification_status"] = VERIFICATION_PENDING
        self.assertIn("verified-genuine", verification_gate(self.lead, self.config))

    def test_rejected_lead_is_blocked(self):
        self.lead["verification_status"] = VERIFICATION_REJECTED
        self.assertIn("rejected_fraud", verification_gate(self.lead, self.config))

    def test_fraud_flags_block_even_if_status_says_verified(self):
        self.lead["fraud_indicators"] = "asks for a registration fee"
        self.assertIn("Fraud screening", verification_gate(self.lead, self.config))

    def test_do_not_contact_blocks(self):
        self.lead["do_not_contact"] = "true"
        self.assertIn("do-not-contact", verification_gate(self.lead, self.config))

    def test_missing_legal_basis_blocks_when_policy_is_set(self):
        self.lead["legal_basis"] = ""
        self.assertIn("legal basis", verification_gate(self.lead, self.config))

    def test_stale_verification_blocks(self):
        self.lead["verification_checked_at"] = "2020-01-01T00:00:00Z"
        self.assertIn("pipeline_verify", verification_gate(self.lead, self.config))

    def test_unverified_email_blocks(self):
        self.lead["email_status"] = "unknown"
        self.assertIn("contact is no longer verified", verification_gate(self.lead, self.config))

    def test_drafting_requires_verification(self):
        drafts, reasons = prepare_drafts(
            genuine_lead(website="https://bit.ly/abc"),
            {
                "subject": "Website project",
                "email_body": (
                    "Hello,\n\nI saw your published website requirement and can share a short plan. "
                    "Portfolio: https://portfolio.example.com/\n\nKind regards,\nTest Owner"
                ),
            },
            self.config,
            [],
            include_whatsapp=False,
        )
        self.assertEqual(drafts, [])
        self.assertTrue(any("Verification" in reason for reason in reasons))

    def test_send_gate_blocks_pending_verification(self):
        draft = {
            "draft_id": "draft-1",
            "lead_id": "lead-1",
            "channel": "email",
            "recipient": "info@acme.com",
            "subject": "Website project",
            "body": (
                "Hello,\n\nI noticed your published requirement for a new business website. "
                "I build responsive sites and can share a short plan if the project is still open. "
                "Examples: https://portfolio.example.com/\n\nIf this is already handled, no reply is needed.\n\n"
                "Kind regards,\nTest Owner"
            ),
            "approval_status": APPROVAL_APPROVED,
            "approved_by": "owner@example.com",
            "approved_at": now_iso(),
        }
        enabled = temp_config(outreach_send_enabled=True)
        qualified = dict(self.lead, qualification_status="qualified", qualification_score="88")
        self.assertTrue(approval_gate(draft, qualified, enabled, [draft])[0])
        held = dict(qualified, verification_status=VERIFICATION_PENDING)
        ok, reason = approval_gate(draft, held, enabled, [draft])
        self.assertFalse(ok)
        self.assertIn("verified", reason.lower())


class StageTests(unittest.TestCase):
    def test_stage_verify_records_levels_and_suppresses_queued_drafts(self):
        config = temp_config()
        leads_table(config.leads_csv).upsert(
            [
                genuine_lead(),
                genuine_lead(
                    lead_id="lead-2",
                    company_name="Fast Cash Projects",
                    website="https://bit.ly/pay",
                    domain="bit.ly",
                    source_url="https://bit.ly/pay",
                    email="cash@mailinator.com",
                    notes="Registration fee required before project start.",
                ),
            ]
        )
        outreach_table(config.outreach_csv).upsert(
            [
                {
                    "draft_id": "draft-pending",
                    "lead_id": "lead-2",
                    "channel": "email",
                    "recipient": "cash@mailinator.com",
                    "subject": "Project",
                    "body": "Hello",
                    "approval_status": APPROVAL_PENDING,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                },
                {
                    "draft_id": "draft-approved",
                    "lead_id": "lead-2",
                    "channel": "email",
                    "recipient": "cash@mailinator.com",
                    "subject": "Project",
                    "body": "Hello",
                    "approval_status": APPROVAL_APPROVED,
                    "approved_by": "owner@example.com",
                    "approved_at": now_iso(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                },
                {
                    "draft_id": "draft-sent",
                    "lead_id": "lead-2",
                    "channel": "email",
                    "recipient": "cash@mailinator.com",
                    "subject": "Project",
                    "body": "Hello",
                    "approval_status": APPROVAL_SENT,
                    "sent_at": now_iso(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                },
            ]
        )

        result = stage_verify(config)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["drafts_suppressed"], 2)

        rows = {row["lead_id"]: row for row in leads_table(config.leads_csv).load()}
        self.assertEqual(rows["lead-1"]["verification_status"], VERIFICATION_VERIFIED)
        self.assertEqual(rows["lead-2"]["verification_status"], VERIFICATION_REJECTED)
        self.assertTrue(rows["lead-1"]["verified_at"])
        self.assertTrue(json.loads(rows["lead-1"]["verification_checks"]))

        drafts = {row["draft_id"]: row for row in outreach_table(config.outreach_csv).load()}
        self.assertEqual(drafts["draft-pending"]["approval_status"], "suppressed")
        self.assertEqual(drafts["draft-approved"]["approval_status"], "suppressed")
        self.assertIn("Verification:", drafts["draft-pending"]["failure_reason"])
        self.assertEqual(drafts["draft-sent"]["approval_status"], APPROVAL_SENT)

        events = [row["event_type"] for row in activity_table(config.activity_csv).load()]
        self.assertIn("verify_completed", events)
        self.assertIn("verification_changed", events)
        self.assertIn("draft_suppressed", events)

    def test_queue_approved_after_rejection_is_still_suppressed(self):
        config = temp_config()
        leads_table(config.leads_csv).upsert(
            [
                genuine_lead(
                    website="https://bit.ly/x",
                    domain="bit.ly",
                    source_url="https://bit.ly/x",
                    email="cash@mailinator.com",
                )
            ]
        )
        stage_verify(config)  # first run marks it rejected_fraud
        outreach_table(config.outreach_csv).upsert(
            [
                {
                    "draft_id": "late-draft",
                    "lead_id": "lead-1",
                    "channel": "email",
                    "recipient": "cash@mailinator.com",
                    "subject": "Project",
                    "body": "Hello",
                    "approval_status": APPROVAL_APPROVED,
                    "approved_by": "owner@example.com",
                    "approved_at": now_iso(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
            ]
        )
        second = stage_verify(config)
        self.assertEqual(second["status_changes"], 0)
        self.assertEqual(second["drafts_suppressed"], 1)
        draft = outreach_table(config.outreach_csv).load()[0]
        self.assertEqual(draft["approval_status"], "suppressed")

    def test_stage_verify_is_idempotent(self):
        config = temp_config()
        leads_table(config.leads_csv).upsert([genuine_lead()])
        first = stage_verify(config)
        second = stage_verify(config)
        self.assertEqual(first["verified"], 1)
        self.assertEqual(second["verified"], 1)
        self.assertEqual(second["status_changes"], 0)

    def test_dashboard_exposes_verification_without_contact_details(self):
        config = temp_config()
        leads_table(config.leads_csv).upsert(
            [
                genuine_lead(),
                genuine_lead(
                    lead_id="lead-2",
                    company_name="Fake Buyer",
                    website="https://bit.ly/x",
                    domain="bit.ly",
                    email="fake@mailinator.com",
                    source_url="https://bit.ly/x",
                    notes="Pay to apply: registration fee needed.",
                ),
            ]
        )
        stage_verify(config)
        payload = build_dashboard(config)
        self.assertEqual(payload["verification"]["verified_genuine"], 1)
        self.assertEqual(payload["verification"]["rejected_fraud"], 1)
        self.assertEqual(payload["totals"]["verified_genuine"], 1)
        self.assertEqual(payload["totals"]["rejected_fraud"], 1)
        self.assertEqual(payload["verification"]["recent_rejections"][0]["company"], "Fake Buyer")
        self.assertEqual(payload["settings"]["owner_approval_required"], True)
        serialized = json.dumps(payload)
        self.assertNotIn("info@acme.com", serialized)
        self.assertNotIn("fake@mailinator.com", serialized)


if __name__ == "__main__":
    unittest.main()
