"""Offline end-to-end pipeline test with fake Apollo/Hunter/Gemini/SMTP providers."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from genieagent.models import APPROVAL_APPROVED
from genieagent.pipeline import (
    build_dashboard,
    stage_discover,
    stage_draft,
    stage_enrich,
    stage_import_candidates,
    stage_qualify,
    stage_send,
)
from genieagent.storage.csv_store import leads_table, outreach_table
from genieagent.util import now_iso
from tests.helpers import FakeApollo, FakeGemini, FakeHunter, FakeSMTP, temp_config


RESEARCH_COLUMNS = [
    "company",
    "country",
    "contact",
    "contact_url",
    "email",
    "contactMethod",
    "paidSignal",
    "website",
    "source",
    "discovery_method",
    "service",
    "status",
    "evidence",
    "notes",
    "needStage",
    "contactVerified",
    "clientNeedConfirmed",
    "needEvidenceUrl",
    "financialApproved",
    "discovered_at",
    "contactVerificationMethod",
    "phone",
    "phone_source",
]


class PipelineEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="genie-e2e-"))
        self.config = temp_config(self.root, apollo_keyword_tags=("retail", "web design"), apollo_locations=("United States",))
        self.research_csv = self.root / "research_candidates.csv"
        row = {
            "company": "Acme Retail",
            "country": "USA",
            "contact": "",
            "contact_url": "https://acme.com/contact",
            "email": "info@acme.com",
            "contactMethod": "Public email",
            "paidSignal": "Yes",
            "website": "https://acme.com",
            "source": "https://acme.com/project",
            "discovery_method": "test",
            "service": "Website / web application development",
            "status": "Qualified lead",
            "evidence": "Direct requirement: we need a new website for our retail business and have a budget of 5000 USD.",
            "notes": "Public buyer requirement.",
            "needStage": "Client need confirmed",
            "contactVerified": "Yes",
            "clientNeedConfirmed": "Yes",
            "needEvidenceUrl": "https://acme.com/project",
            "financialApproved": "No",
            "discovered_at": now_iso(),
            "contactVerificationMethod": "Public email displayed",
            "phone": "",
            "phone_source": "",
        }
        with open(self.research_csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESEARCH_COLUMNS)
            writer.writeheader()
            writer.writerow(row)

    def test_full_offline_flow(self):
        # A/D: import buyer evidence into leads.csv
        imported = stage_import_candidates(self.config, source=self.research_csv)
        self.assertEqual(imported["status"], "ok")
        leads = leads_table(self.config.leads_csv).load()
        self.assertEqual(len(leads), 1)
        lead = leads[0]
        self.assertEqual(lead["email_status"], "unverified")

        # B: Apollo discovery adds a company record with no stated need
        apollo = FakeApollo([{"id": "org-2", "name": "Beta Dental", "primary_domain": "betadental.com", "country": "USA"}])
        discovered = stage_discover(self.config, apollo=apollo)
        self.assertEqual(discovered["found"], 1)
        after_discover = leads_table(self.config.leads_csv).load()
        self.assertEqual(len(after_discover), 2)

        # C: Hunter verification of the existing public email
        hunter = FakeHunter(emails=[{"value": "info@acme.com", "verification": {"status": "valid"}, "confidence": 95, "type": "generic"}])
        enriched = stage_enrich(self.config, hunter=hunter)
        self.assertGreaterEqual(enriched["verified"], 1)
        lead = next(row for row in leads_table(self.config.leads_csv).load() if row["domain"] == "acme.com")
        self.assertEqual(lead["email_status"], "valid")
        self.assertTrue(lead["email_verified_at"])

        # E: qualification uses recorded evidence only
        gemini = FakeGemini(score=91)
        qualified = stage_qualify(self.config, gemini=gemini)
        self.assertEqual(qualified["qualified"], 1)
        self.assertGreaterEqual(qualified["blocked_without_evidence"], 1)
        leads = leads_table(self.config.leads_csv).load()
        acme = next(row for row in leads if row["domain"] == "acme.com")
        beta = next(row for row in leads if row["domain"] == "betadental.com")
        self.assertEqual(acme["qualification_status"], "qualified")
        self.assertEqual(beta["qualification_status"], "needs_review")

        # F/I/J: drafts queued, never sent
        drafted = stage_draft(self.config, gemini=gemini)
        self.assertGreaterEqual(drafted["drafts_created"], 1)
        drafts = outreach_table(self.config.outreach_csv).load()
        self.assertTrue(drafts)
        self.assertTrue(all(draft["approval_status"] == "pending_owner_approval" for draft in drafts))

        # Safety: sending disabled by default
        preview = stage_send(self.config, dry_run=True)
        self.assertEqual(preview["status"], "skipped")

        # Owner approves exactly one draft (as pipeline_approve.py would)
        draft = drafts[0]
        table = outreach_table(self.config.outreach_csv)
        table.update(
            draft["draft_id"],
            approval_status=APPROVAL_APPROVED,
            approved_by="owner@example.com",
            approved_at=now_iso(),
        )

        # Still disabled until the owner explicitly enables sending
        still_disabled = stage_send(self.config, dry_run=False)
        self.assertEqual(still_disabled["status"], "skipped")

        enabled = temp_config(
            self.root,
            outreach_send_enabled=True,
            owner_email="owner@example.com",
            portfolio_url="https://portfolio.example.com/",
            brevo_smtp_login="login@example.com",
            brevo_smtp_key="test-smtp-key",
            brevo_sender_email="owner@example.com",
        )
        smtp = FakeSMTP()
        sent = stage_send(enabled, dry_run=False, smtp=smtp)
        self.assertEqual(sent["sent"], 1, json.dumps(sent, indent=2))
        self.assertEqual(len(smtp.sent), 1)
        self.assertNotIn("{{", smtp.sent[0]["body"])
        lead_after = next(row for row in leads_table(enabled.leads_csv).load() if row["domain"] == "acme.com")
        self.assertEqual(lead_after["outreach_status"], "sent")

        # A second run must not duplicate the send
        again = stage_send(enabled, dry_run=False, smtp=smtp)
        self.assertEqual(again["sent"], 0)

        # Dashboard export has no contact details
        payload = build_dashboard(enabled)
        serialized = json.dumps(payload)
        self.assertNotIn("info@acme.com", serialized)
        self.assertEqual(payload["totals"]["messages_sent"], 1)

    def test_send_blocks_unverified_leads(self):
        stage_import_candidates(self.config, source=self.research_csv)
        gemini = FakeGemini(score=95)
        stage_qualify(self.config, gemini=gemini)
        # A draft cannot even be prepared for an unverified address.
        self.assertEqual(stage_draft(self.config, gemini=gemini)["drafts_created"], 0)
        lead = leads_table(self.config.leads_csv).load()[0]
        # Simulate a draft that an operator forced in by hand.
        draft = {
            "draft_id": "forced-draft",
            "lead_id": lead["lead_id"],
            "channel": "email",
            "provider": "brevo_smtp",
            "recipient": lead["email"],
            "subject": "Website project for Acme Retail",
            "body": "Hello, I saw your website requirement. Portfolio: https://portfolio.example.com/",
            "approval_status": APPROVAL_APPROVED,
            "approved_by": "owner@example.com",
            "approved_at": now_iso(),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        outreach_table(self.config.outreach_csv).upsert([draft])
        config = temp_config(
            self.root,
            outreach_send_enabled=True,
            owner_email="owner@example.com",
            portfolio_url="https://portfolio.example.com/",
            brevo_smtp_login="login@example.com",
            brevo_smtp_key="test-smtp-key",
            brevo_sender_email="owner@example.com",
        )
        result = stage_send(config, dry_run=False, smtp=FakeSMTP())
        self.assertEqual(result["sent"], 0)
        self.assertGreaterEqual(result["blocked"], 1)


if __name__ == "__main__":
    unittest.main()
