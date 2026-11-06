"""Draft creation and the owner-approval gate.

Every outbound message must pass :func:`approval_gate`. There is deliberately no
code path that marks its own draft approved.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import Config
from ..models import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_SENT,
    APPROVAL_SUPPRESSED,
    LEAD_STATUS_QUALIFIED,
    OUTREACH_BOUNCED,
    OUTREACH_OPTED_OUT,
    OUTREACH_SENT,
    PROVIDER_EMAIL,
    PROVIDER_GREEN,
    PROVIDER_META,
    SENDABLE_EMAIL_STATUSES,
)
from ..providers.gemini import validate_draft
from ..qualify import email_is_contactable
from ..util import days_since, mask_recipient, now_iso, stable_id


def provider_for_channel(config: Config, channel: str) -> str:
    if channel == "email":
        return PROVIDER_EMAIL
    if channel == "whatsapp":
        if config.whatsapp_provider == "green_api":
            return PROVIDER_GREEN
        return PROVIDER_META
    return ""


def _existing(rows: Iterable[Dict[str, Any]], lead_id: str, channel: str) -> List[Dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("lead_id") or "") == str(lead_id) and str(row.get("channel") or "") == channel
    ]


def already_contacted(rows: Iterable[Dict[str, Any]], lead_id: str, channel: str) -> bool:
    for row in _existing(rows, lead_id, channel):
        if str(row.get("approval_status") or "") in {APPROVAL_SENT, "sent_pending_verification"}:
            return True
        if str(row.get("sent_at") or "").strip():
            return True
    return False


def prepare_drafts(
    lead: Dict[str, Any],
    generated: Dict[str, Any],
    config: Config,
    existing_drafts: Sequence[Dict[str, Any]],
    include_whatsapp: bool = True,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Turn a validated AI draft into pending-approval rows (never approved)."""
    drafts: List[Dict[str, Any]] = []
    skipped: List[str] = []
    lead_id = str(lead.get("lead_id") or "")
    if not lead_id:
        return drafts, ["Lead has no lead_id."]

    portfolio = config.portfolio_url or ""
    problems = validate_draft(generated, portfolio_url=portfolio)
    if problems:
        return drafts, problems

    timestamp = now_iso()
    subject = str(generated.get("subject") or "").strip()
    email_body = str(generated.get("email_body") or "").strip()
    whatsapp_body = str(generated.get("whatsapp_body") or "").strip()

    if not email_is_contactable(lead):
        skipped.append("Email is missing or not verified; no email draft created.")
    elif already_contacted(existing_drafts, lead_id, "email"):
        skipped.append("Lead already has an email draft or send on record.")
    elif any(
        row.get("approval_status") in {APPROVAL_PENDING, APPROVAL_APPROVED}
        for row in _existing(existing_drafts, lead_id, "email")
    ):
        skipped.append("An email draft for this lead is already awaiting approval.")
    else:
        drafts.append(
            _draft_row(
                lead,
                "email",
                provider_for_channel(config, "email"),
                str(lead.get("email") or ""),
                subject,
                email_body,
                timestamp,
            )
        )

    if include_whatsapp:
        reason = whatsapp_draft_blocker(lead, config)
        if reason:
            skipped.append(reason)
        elif not whatsapp_body:
            skipped.append("AI draft has no WhatsApp variant.")
        elif already_contacted(existing_drafts, lead_id, "whatsapp"):
            skipped.append("Lead already has a WhatsApp draft or send on record.")
        else:
            drafts.append(
                _draft_row(
                    lead,
                    "whatsapp",
                    provider_for_channel(config, "whatsapp"),
                    str(lead.get("phone_business") or ""),
                    subject,
                    whatsapp_body,
                    timestamp,
                )
            )
    return drafts, skipped


def whatsapp_draft_blocker(lead: Dict[str, Any], config: Config) -> str:
    if config.whatsapp_provider == "none":
        return "WhatsApp provider is not configured (WHATSAPP_PROVIDER=none)."
    if not config.whatsapp_ready:
        return "WhatsApp provider credentials are incomplete."
    phone = str(lead.get("phone_business") or "").strip()
    if not phone:
        return "No business phone number on record; personal numbers must never be used."
    if str(lead.get("phone_type") or "").strip().lower() != "business":
        return "Phone number is not recorded as a business number."
    if not str(lead.get("consent_basis") or "").strip():
        return "No documented consent basis; WhatsApp outreach requires one."
    if str(lead.get("do_not_contact") or "").lower() == "true":
        return "Lead is marked do-not-contact."
    return ""


def _draft_row(
    lead: Dict[str, Any],
    channel: str,
    provider: str,
    recipient: str,
    subject: str,
    body: str,
    timestamp: str,
    follow_up_of: str = "",
) -> Dict[str, str]:
    draft_id = stable_id("draft", lead.get("lead_id", ""), channel, follow_up_of or "initial", timestamp[:10])
    return {
        "draft_id": draft_id,
        "lead_id": str(lead.get("lead_id") or ""),
        "channel": channel,
        "provider": provider,
        "recipient": recipient,
        "recipient_masked": mask_recipient(channel, recipient),
        "subject": subject,
        "body": body,
        "approval_status": APPROVAL_PENDING,
        "approved_by": "",
        "approved_at": "",
        "sent_at": "",
        "provider_message_id": "",
        "delivery_status": "not_sent",
        "failure_reason": "",
        "follow_up_of": follow_up_of,
        "attempt_count": "0",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


# --------------------------------------------------------------------- gate


def approval_gate(
    draft: Dict[str, Any],
    lead: Dict[str, Any],
    config: Config,
    all_drafts: Sequence[Dict[str, Any]],
    unattended: bool = False,
) -> Tuple[bool, str]:
    """Single source of truth for whether a message may leave the machine."""
    status = str(draft.get("approval_status") or "").strip().lower()
    if status != APPROVAL_APPROVED:
        return False, f"Draft approval_status is '{status or 'empty'}', not 'approved'."
    if not str(draft.get("approved_by") or "").strip():
        return False, "Draft has no approver recorded."
    if config.owner_email and str(draft.get("approved_by") or "").strip().lower() != config.owner_email.lower():
        return False, "Draft was not approved by the configured owner email."
    if not str(draft.get("approved_at") or "").strip():
        return False, "Draft has no approval timestamp."
    if not config.outreach_send_enabled:
        return False, "OUTREACH_SEND_ENABLED is false; sending is disabled."
    if unattended and not config.auto_outreach_enabled:
        return False, "Unattended sending requires AUTO_OUTREACH_ENABLED=true."

    lead_status = str(lead.get("qualification_status") or "")
    if lead_status != LEAD_STATUS_QUALIFIED:
        return False, f"Lead qualification_status is '{lead_status or 'empty'}', not qualified."
    try:
        score = int(float(str(lead.get("qualification_score") or 0)))
    except ValueError:
        score = 0
    if score < int(config.outreach_min_score):
        return False, f"Qualification score {score} is below OUTREACH_MIN_SCORE={config.outreach_min_score}."
    if str(lead.get("do_not_contact") or "").lower() == "true":
        return False, "Lead is marked do-not-contact."
    if str(lead.get("outreach_status") or "") in {OUTREACH_OPTED_OUT, OUTREACH_BOUNCED}:
        return False, "Lead opted out or bounced previously."
    if already_contacted([row for row in all_drafts if row.get("draft_id") != draft.get("draft_id")], str(lead.get("lead_id") or ""), str(draft.get("channel") or "")):
        return False, "Another draft for this lead and channel was already sent."

    channel = str(draft.get("channel") or "")
    if channel == "email":
        if not config.brevo_ready:
            return False, "Brevo SMTP is not fully configured."
        email = str(lead.get("email") or "").strip().lower()
        if not email:
            return False, "Lead has no email address."
        if str(lead.get("email_status") or "").lower() not in SENDABLE_EMAIL_STATUSES:
            return False, f"Email status '{lead.get('email_status') or 'unverified'}' is not verified/valid."
        if not str(lead.get("email_verified_at") or "").strip():
            return False, "Email has no verification timestamp."
        if email in {item.lower() for item in config.suppressed_emails}:
            return False, "Recipient is on the suppression list."
        if str(draft.get("recipient") or "").strip().lower() != email:
            return False, "Draft recipient does not match the verified lead email."
        if not str(draft.get("subject") or "").strip() or not str(draft.get("body") or "").strip():
            return False, "Draft subject or body is empty."
        problems = validate_draft(
            {"subject": draft.get("subject"), "email_body": draft.get("body")},
            portfolio_url=config.portfolio_url,
        )
        if problems:
            return False, "Draft validation failed: " + " ".join(problems)
        return True, ""

    if channel == "whatsapp":
        if not config.whatsapp_send_enabled:
            return False, "WHATSAPP_SEND_ENABLED is false; WhatsApp sending is disabled."
        if not config.whatsapp_ready:
            return False, "WhatsApp provider is not configured."
        blocker = whatsapp_draft_blocker(lead, config)
        if blocker:
            return False, blocker
        if config.whatsapp_provider == "meta_cloud" and not config.whatsapp_meta_template_name:
            return False, "Meta Cloud API requires an approved template for first contact."
        if not str(draft.get("body") or "").strip():
            return False, "WhatsApp draft body is empty."
        return True, ""

    return False, f"Unknown channel '{channel}'."


def rejected_status_for(reason: str) -> str:
    if "suppression" in reason.lower() or "do-not-contact" in reason.lower() or "opted out" in reason.lower():
        return APPROVAL_SUPPRESSED
    return APPROVAL_REJECTED


# ---------------------------------------------------------------- follow ups


def plan_follow_up(
    lead: Dict[str, Any],
    lead_drafts: Sequence[Dict[str, Any]],
    config: Config,
) -> Tuple[bool, str, str]:
    """Return (needs_follow_up, previous_draft_id, reason). Drafts only; never sent here.

    The anchor is the initial email (or the most recent sent follow-up), so the
    configured day thresholds (5/12/21 by default) are spaced correctly.
    """
    if not email_is_contactable(lead):
        return False, "", "Lead email is not verified."
    if str(lead.get("outreach_status") or "") in {OUTREACH_OPTED_OUT, OUTREACH_BOUNCED}:
        return False, "", "Lead opted out or bounced."
    if str(lead.get("last_reply_at") or "").strip():
        return False, "", "Lead already replied."
    email_drafts = [row for row in lead_drafts if row.get("channel") == "email"]
    sent_initial = [row for row in email_drafts if not row.get("follow_up_of") and row.get("sent_at")]
    if not sent_initial:
        return False, "", "No sent initial email on record."
    if any(row.get("approval_status") == APPROVAL_PENDING and row.get("follow_up_of") for row in email_drafts):
        return False, "", "A follow-up draft is already awaiting approval."
    sequence = tuple(config.outreach_followup_days or (5, 12, 21))
    sent_follow_ups = sorted(
        [row for row in email_drafts if row.get("follow_up_of") and row.get("sent_at")],
        key=lambda row: str(row.get("sent_at") or ""),
    )
    if len(sent_follow_ups) >= len(sequence):
        return False, "", "All follow-ups used."
    anchor = sent_follow_ups[-1] if sent_follow_ups else sent_initial[0]
    elapsed = days_since(anchor.get("sent_at"))
    if elapsed is None:
        return False, "", "Last send time is unreadable."
    threshold = sequence[len(sent_follow_ups)]
    if elapsed < threshold:
        return False, "", f"Follow-up not due for {threshold - elapsed:.1f} more day(s)."
    return True, str(anchor.get("draft_id") or ""), f"Follow-up {len(sent_follow_ups) + 1} due after {threshold} day(s)."


def normalize_approval_value(value: Any) -> str:
    text = re.sub(r"\s+", "_", str(value or "").strip().lower())
    aliases = {
        "approve": APPROVAL_APPROVED,
        "approved": APPROVAL_APPROVED,
        "yes": APPROVAL_APPROVED,
        "pending": APPROVAL_PENDING,
        "pending_owner_approval": APPROVAL_PENDING,
        "reject": APPROVAL_REJECTED,
        "rejected": APPROVAL_REJECTED,
        "no": APPROVAL_REJECTED,
        "suppressed": APPROVAL_SUPPRESSED,
        "sent": APPROVAL_SENT,
    }
    return aliases.get(text, text)
