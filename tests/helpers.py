"""Test helpers: temporary configs and fake providers (no network calls)."""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from genieagent.config import Config
from genieagent.outreach.brevo import EmailSendResult


def temp_config(base: Optional[Path] = None, **overrides: Any) -> Config:
    root = Path(base or tempfile.mkdtemp(prefix="genieagent-test-"))
    defaults: Dict[str, Any] = dict(
        data_dir=root,
        leads_csv=root / "leads.csv",
        outreach_csv=root / "outreach.csv",
        activity_csv=root / "activity.csv",
        dashboard_json=root / "dashboard.json",
        owner_email="owner@example.com",
        owner_name="Test Owner",
        portfolio_url="https://portfolio.example.com/",
        outreach_send_enabled=False,
        auto_outreach_enabled=False,
        suppressed_emails=(),
        whatsapp_provider="none",
        whatsapp_send_enabled=False,
        brevo_smtp_host="smtp-relay.brevo.com",
        brevo_smtp_port=587,
        brevo_smtp_login="login@example.com",
        brevo_smtp_key="test-smtp-key",
        brevo_sender_email="owner@example.com",
    )
    defaults.update(overrides)
    return dataclasses.replace(Config(), **defaults)


class FakeSMTP:
    def __init__(self, fail: bool = False) -> None:
        self.sent: List[Dict[str, str]] = []
        self.fail = fail

    def send(self, to: str, subject: str, body: str, reply_to: str = "", dry_run: bool = False) -> EmailSendResult:
        if self.fail:
            return EmailSendResult(False, "failed", detail="Simulated SMTP failure")
        if dry_run:
            return EmailSendResult(True, "dry_run", detail="dry run", accepted=[to])
        self.sent.append({"to": to, "subject": subject, "body": body, "reply_to": reply_to})
        return EmailSendResult(True, "smtp_accepted", provider_message_id="<fake@example.com>", detail="accepted", accepted=[to])


class FakeApollo:
    def __init__(self, organizations: List[Dict[str, Any]]) -> None:
        self.organizations = organizations
        self.calls = 0

    def search_companies(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.calls += 1
        return list(self.organizations)

    def company_to_lead(self, organization: Dict[str, Any]) -> Dict[str, str]:
        from genieagent.providers.apollo import ApolloClient

        # Reuse the real mapping without constructing a network client.
        return ApolloClient.company_to_lead(None, organization)  # type: ignore[arg-type]


class FakeHunter:
    def __init__(self, emails: Optional[List[Dict[str, Any]]] = None, verify_status: str = "valid") -> None:
        self.emails = emails or []
        self.verify_status = verify_status
        self.verified: List[str] = []

    def verify_email(self, email: str) -> Dict[str, Any]:
        self.verified.append(email)
        return {"email": email, "status": self.verify_status, "score": 95, "verification": {"date": "2026-01-01"}}

    def domain_search(self, domain: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.emails

    def choose_business_email(self, domain: str, candidates: List[Dict[str, Any]], verify: bool = True) -> Dict[str, Any]:
        from genieagent.providers.hunter import HunterClient

        return HunterClient.choose_business_email(None, domain, candidates, verify=False)  # type: ignore[arg-type]


class FakeGemini:
    def __init__(self, score: int = 88, qualified: bool = True) -> None:
        self.score = score
        self.qualified = qualified
        self.calls = 0

    def qualify_lead(self, lead: Dict[str, Any], min_score: int = 70) -> Dict[str, Any]:
        self.calls += 1
        return {
            "qualified": self.qualified,
            "score": self.score,
            "service_fit": "Website development",
            "need_summary": "Needs a new business website.",
            "reasoning": "The source states a concrete website project with budget.",
            "risks": [],
            "recommended_angle": "Offer a scoped landing page.",
            "evidence_quotes": ["need a new website"],
        }

    def draft_outreach(self, lead: Dict[str, Any], sender_name: str = "", portfolio_url: str = "") -> Dict[str, Any]:
        return {
            "subject": f"Website project for {lead.get('company_name')}",
            "email_body": (
                "Hello,\n\nI noticed your published requirement for a new business website. "
                "I build responsive sites and can share a short plan if the project is still open. "
                f"Examples: {portfolio_url}\n\nIf this is already handled, no reply is needed.\n\nKind regards,\n"
                f"{sender_name}"
            ),
            "whatsapp_body": "Hello, I saw your website project request. Is it still open for a quick scope discussion?",
            "personalization_notes": "References the published requirement.",
        }

    def draft_follow_up(self, lead: Dict[str, Any], previous_subject: str = "", sender_name: str = "", portfolio_url: str = "") -> Dict[str, Any]:
        draft = self.draft_outreach(lead, sender_name, portfolio_url)
        draft["subject"] = "Following up: " + str(previous_subject or "your website project")
        draft["email_body"] = (
            "Hello,\n\nA short follow-up on the website requirement I mentioned earlier. "
            "If it is still active I can send a one-page outline; if not, no action needed. "
            f"Portfolio: {portfolio_url}\n\nKind regards,\n{sender_name}"
        )
        return draft
