"""Send one approved draft through its configured provider.

This module is deliberately dumb: it performs no approval checks of its own.
Approval is enforced by :func:`genieagent.outreach.drafts.approval_gate`, which
callers must run first (and the pipeline does).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config import Config
from ..util import now_iso
from .brevo import BrevoSMTP, smtp_from_config
from .whatsapp import MetaCloudProvider, build_provider


@dataclass
class SendOutcome:
    ok: bool
    status: str
    detail: str
    provider_message_id: str = ""
    delivery_status: str = "not_sent"
    mode: str = "text"


def send_draft(
    draft: Dict[str, Any],
    lead: Dict[str, Any],
    config: Config,
    smtp: Optional[BrevoSMTP] = None,
    whatsapp_provider: Optional[Any] = None,
    dry_run: bool = False,
) -> SendOutcome:
    channel = str(draft.get("channel") or "")
    reply_to = config.owner_email or config.sender_email
    if channel == "email":
        client = smtp or smtp_from_config(config)
        result = client.send(
            str(draft.get("recipient") or lead.get("email") or ""),
            str(draft.get("subject") or ""),
            str(draft.get("body") or ""),
            reply_to=reply_to,
            dry_run=dry_run,
        )
        if not result.ok:
            return SendOutcome(False, result.status, result.detail)
        return SendOutcome(
            True,
            "sent",
            result.detail,
            provider_message_id=result.provider_message_id,
            delivery_status=result.status,
        )

    if channel == "whatsapp":
        provider = whatsapp_provider if whatsapp_provider is not None else build_provider(config)
        if provider is None:
            return SendOutcome(False, "failed", "WhatsApp provider is not configured.")
        if dry_run:
            return SendOutcome(True, "sent", "Dry run: WhatsApp message prepared but not sent.", delivery_status="dry_run")
        recipient = str(draft.get("recipient") or lead.get("phone_business") or "")
        if isinstance(provider, MetaCloudProvider):
            params = [
                str(lead.get("contact_name") or lead.get("company_name") or "there"),
                str(lead.get("service_fit") or "your project"),
            ]
            result = provider.send_template(recipient, params)
        else:
            result = provider.send_text(recipient, str(draft.get("body") or ""))
        if not result.ok:
            return SendOutcome(False, result.status, result.detail)
        return SendOutcome(
            True,
            "sent",
            result.detail,
            provider_message_id=result.message_id,
            delivery_status=result.status,
            mode=result.mode,
        )

    return SendOutcome(False, "failed", f"Unknown channel '{channel}'.")


def apply_outcome(draft: Dict[str, Any], outcome: SendOutcome, attempt: int = 1) -> Dict[str, Any]:
    """Record a send attempt on the draft row (mutates and returns it)."""
    timestamp = now_iso()
    draft["attempt_count"] = str(attempt)
    draft["updated_at"] = timestamp
    if outcome.ok:
        draft["approval_status"] = "sent"
        draft["sent_at"] = timestamp
        draft["delivery_status"] = outcome.delivery_status or "sent"
        draft["provider_message_id"] = outcome.provider_message_id
        draft["failure_reason"] = ""
    else:
        draft["approval_status"] = "failed"
        draft["failure_reason"] = outcome.detail[:500]
        draft["delivery_status"] = "failed"
    return draft


def lead_after_send(lead: Dict[str, Any], draft: Dict[str, Any], status: str = "sent") -> Dict[str, Any]:
    lead["outreach_status"] = status
    lead["last_contact_at"] = now_iso()
    lead["updated_at"] = now_iso()
    if draft.get("channel") == "whatsapp":
        lead["whatsapp_status"] = "sent"
    return lead
