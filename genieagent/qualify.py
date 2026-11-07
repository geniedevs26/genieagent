"""Qualification gates shared by scripts and tests.

A lead is only eligible for AI qualification when a real, source-linked business
requirement exists. Apollo company records alone are not a stated need.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import (
    LEAD_STATUS_NEEDS_REVIEW,
    LEAD_STATUS_QUALIFIED,
    LEAD_STATUS_REJECTED,
    SENDABLE_EMAIL_STATUSES,
)

APOLLO_ONLY_NOTE = "Company record from Apollo"


def requirement_evidence(lead: Dict[str, Any]) -> str:
    """Return the source-linked evidence text, or empty when none exists."""
    notes = str(lead.get("notes") or "").strip()
    if notes.startswith(APOLLO_ONLY_NOTE):
        return ""
    pieces = [
        str(lead.get("need_summary") or "").strip(),
        notes,
        str(lead.get("qualification_reason") or "").strip(),
    ]
    evidence = " ".join(piece for piece in pieces if piece).strip()
    if len(evidence) < 40:
        return ""
    # The requirement itself must be source-linked. A company homepage is not a
    # stated requirement, so ``website`` is deliberately not used as a fallback.
    source = str(lead.get("source_url") or "").strip()
    if not source.startswith("http"):
        return ""
    return evidence


def qualification_gate(lead: Dict[str, Any]) -> Optional[str]:
    """Return a blocking reason, or None when the lead can be qualified."""
    if str(lead.get("do_not_contact") or "").lower() == "true":
        return "Lead is marked do-not-contact."
    if not requirement_evidence(lead):
        return "No source-linked business requirement is recorded; qualification would be invented."
    return None


def apply_qualification(lead: Dict[str, Any], result: Dict[str, Any], min_score: int = 70) -> Dict[str, Any]:
    """Merge a validated Gemini result into a lead record."""
    qualified = bool(result.get("qualified")) and int(result.get("score") or 0) >= int(min_score)
    risks = result.get("risks") or []
    reason_parts = [str(result.get("reasoning") or "").strip()]
    if risks:
        reason_parts.append("Risks: " + "; ".join(str(risk) for risk in risks))
    lead["qualification_score"] = str(int(result.get("score") or 0))
    lead["qualification_status"] = LEAD_STATUS_QUALIFIED if qualified else LEAD_STATUS_REJECTED
    lead["qualification_reason"] = " ".join(part for part in reason_parts if part)[:1200]
    lead["service_fit"] = str(result.get("service_fit") or lead.get("service_fit") or "")[:160]
    lead["need_summary"] = str(result.get("need_summary") or lead.get("need_summary") or "")[:400]
    lead["priority"] = _priority(int(result.get("score") or 0), qualified)
    return lead


def _priority(score: int, qualified: bool) -> str:
    if not qualified:
        return "low"
    if score >= 90:
        return "high"
    if score >= 80:
        return "medium"
    return "review"


def email_is_contactable(lead: Dict[str, Any]) -> bool:
    return (
        bool(str(lead.get("email") or "").strip())
        and str(lead.get("email_status") or "").lower() in SENDABLE_EMAIL_STATUSES
        and bool(str(lead.get("email_verified_at") or "").strip())
        and str(lead.get("do_not_contact") or "").lower() != "true"
    )


def qualification_summary(leads: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"total": len(leads), "qualified": 0, "rejected": 0, "pending": 0, "needs_review": 0, "verified_email": 0}
    for lead in leads:
        status = str(lead.get("qualification_status") or "pending")
        if status in summary:
            summary[status] += 1
        if email_is_contactable(lead):
            summary["verified_email"] += 1
    if str(LEAD_STATUS_NEEDS_REVIEW) not in summary:
        summary[str(LEAD_STATUS_NEEDS_REVIEW)] = 0
    return summary
