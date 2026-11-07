"""Canonical record shapes shared by leads.csv, Google Sheets and the dashboard."""

from __future__ import annotations

from typing import Dict, List, Tuple

LEAD_COLUMNS: List[str] = [
    "lead_id",
    "company_name",
    "normalized_company",
    "domain",
    "website",
    "country",
    "industry",
    "employee_range",
    "contact_name",
    "contact_title",
    "email",
    "email_type",
    "email_status",
    "email_score",
    "email_verified_at",
    "email_source",
    "phone_business",
    "phone_source",
    "phone_type",
    "source_provider",
    "source_url",
    "source_ref",
    "service_fit",
    "qualification_score",
    "qualification_status",
    "qualification_reason",
    "need_summary",
    "priority",
    "outreach_status",
    "follow_up_count",
    "last_contact_at",
    "last_reply_at",
    "order_status",
    "whatsapp_status",
    "do_not_contact",
    "consent_basis",
    "notes",
    # Strict authenticity verification (see genieagent/verification.py)
    "verification_status",
    "verification_reason",
    "identity_status",
    "verification_method",
    "verification_sources",
    "verification_checks",
    "fraud_indicators",
    "legal_basis",
    "verification_checked_at",
    "verified_at",
    "verification_fingerprint",
    "created_at",
    "updated_at",
]

OUTREACH_COLUMNS: List[str] = [
    "draft_id",
    "lead_id",
    "channel",
    "provider",
    "recipient",
    "recipient_masked",
    "subject",
    "body",
    "approval_status",
    "approved_by",
    "approved_at",
    "sent_at",
    "provider_message_id",
    "delivery_status",
    "failure_reason",
    "follow_up_of",
    "attempt_count",
    "created_at",
    "updated_at",
]

ACTIVITY_COLUMNS: List[str] = [
    "event_id",
    "timestamp",
    "event_type",
    "status",
    "lead_id",
    "summary",
    "details",
]

# Lead lifecycle
LEAD_STATUS_NEW = "discovered"
LEAD_STATUS_ENRICHED = "enriched"
LEAD_STATUS_UNVERIFIED = "email_unverified"
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_REJECTED = "rejected"
LEAD_STATUS_NEEDS_REVIEW = "needs_review"

OUTREACH_NOT_CONTACTED = "not_contacted"
OUTREACH_DRAFT_PENDING = "draft_pending_approval"
OUTREACH_APPROVED = "approved"
OUTREACH_SENT = "sent"
OUTREACH_REPLIED = "replied"
OUTREACH_BOUNCED = "bounced"
OUTREACH_OPTED_OUT = "opted_out"
OUTREACH_CLOSED = "closed"

ORDER_NONE = "none"
ORDER_INTERESTED = "interested"
ORDER_PROPOSAL_PENDING = "proposal_pending"
ORDER_PROPOSAL_APPROVED = "proposal_approved"
ORDER_IN_PROGRESS = "in_progress"
ORDER_DELIVERED = "delivered"
ORDER_CLOSED = "closed"
ORDER_LOST = "lost"

ORDER_STATUSES: Tuple[str, ...] = (
    ORDER_NONE,
    ORDER_INTERESTED,
    ORDER_PROPOSAL_PENDING,
    ORDER_PROPOSAL_APPROVED,
    ORDER_IN_PROGRESS,
    ORDER_DELIVERED,
    ORDER_CLOSED,
    ORDER_LOST,
)

# Outreach approval lifecycle (owner-controlled; see docs/ARCHITECTURE.md)
APPROVAL_DRAFT = "draft"
APPROVAL_PENDING = "pending_owner_approval"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_SENT = "sent"
APPROVAL_FAILED = "failed"
APPROVAL_SUPPRESSED = "suppressed"

SENDABLE_EMAIL_STATUSES = ("valid", "deliverable")

# Three-level authenticity verification. Only VERIFIED_GENUINE may be contacted.
VERIFICATION_VERIFIED = "verified_genuine"
VERIFICATION_PENDING = "pending_verification"
VERIFICATION_REJECTED = "rejected_fraud"
VERIFICATION_LEVELS: Tuple[str, ...] = (
    VERIFICATION_VERIFIED,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
)
IDENTITY_MATCHED = "matched"
IDENTITY_UNCONFIRMED = "unconfirmed"
IDENTITY_MISMATCH = "mismatch"
VERIFICATION_METHOD = "recorded_evidence_review_v1"

CHANNELS = ("email", "whatsapp")
PROVIDER_EMAIL = "brevo_smtp"
PROVIDER_META = "meta_cloud_api"
PROVIDER_GREEN = "green_api"

LEAD_DEFAULTS: Dict[str, str] = {
    "email_score": "0",
    "follow_up_count": "0",
    "do_not_contact": "false",
    "outreach_status": OUTREACH_NOT_CONTACTED,
    "order_status": ORDER_NONE,
    "qualification_score": "0",
    "qualification_status": "pending",
    "verification_status": VERIFICATION_PENDING,
    "identity_status": IDENTITY_UNCONFIRMED,
}

OUTREACH_DEFAULTS: Dict[str, str] = {
    "approval_status": APPROVAL_DRAFT,
    "attempt_count": "0",
    "delivery_status": "not_sent",
}

BANNED_DRAFT_MARKERS: Tuple[str, ...] = (
    "{{",
    "}}",
    "[your name]",
    "[company name]",
    "insert ",
    "lorem ipsum",
    "draft for owner review",
    "to be confirmed",
    "your portfolio link",
)


def empty_lead() -> Dict[str, str]:
    return {column: "" for column in LEAD_COLUMNS}


def empty_outreach() -> Dict[str, str]:
    return {column: "" for column in OUTREACH_COLUMNS}
