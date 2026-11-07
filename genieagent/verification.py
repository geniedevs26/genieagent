"""Strict authenticity verification and fraud screening.

This module decides whether a lead is a *genuine* business opportunity using
only data the pipeline has already recorded. It never fetches a page, guesses a
fact or claims a check that did not happen: every decision names the field it
came from, and any missing evidence holds the lead instead of promoting it.

Three levels (see docs/VERIFICATION.md):

* ``verified_genuine``   - identity consistent, requirement source-linked,
                           service matched and a verified business contact.
* ``pending_verification`` - information is missing or a review-level flag was
                           found. Never eligible for outreach.
* ``rejected_fraud``     - a hard contradiction or high-risk indicator (fake
                           domain, disposable mailbox, pay-to-work demand).
                           Never eligible for outreach.

Only ``verified_genuine`` passes :func:`verification_gate`, which is enforced
before drafts are written, before Gemini qualification and again before send.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .models import (
    IDENTITY_MATCHED,
    IDENTITY_MISMATCH,
    IDENTITY_UNCONFIRMED,
    SENDABLE_EMAIL_STATUSES,
    VERIFICATION_METHOD,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
    VERIFICATION_VERIFIED,
)
from .normalize import (
    FREE_MAIL_DOMAINS,
    email_matches_domain,
    is_disposable,
    is_free_mail,
    normalize_domain,
    normalize_email,
)
from .qualify import requirement_evidence
from .util import now_utc, parse_iso

# Websites that are a redirect or a shared free host, not a business identity.
SHORTENER_DOMAINS = frozenset(
    {
        "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
        "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy", "tiny.cc",
    }
)
FREE_SITE_SUFFIXES = (
    "wixsite.com", "blogspot.com", "wordpress.com", "weebly.com", "github.io",
    "web.app", "firebaseapp.com", "godaddysites.com", "business.site",
    "square.site", "carrd.co", "notion.site", "webflow.io", "mystrikingly.com",
)

# Buyer-side demands for money or anonymous payment rails are the classic
# fake-project pattern. Phrases are matched case-insensitively on recorded text.
HIGH_RISK_PHRASES: Tuple[Tuple[str, str], ...] = (
    ("registration fee", "asks for a registration fee"),
    ("joining fee", "asks for a joining fee"),
    ("pay to apply", "asks the seller to pay to apply"),
    ("pay upfront", "demands an upfront payment"),
    ("advance payment", "demands an advance payment"),
    ("processing fee", "charges a processing fee"),
    ("security deposit", "demands a security deposit"),
    ("western union", "requests Western Union"),
    ("gift card", "requests gift cards"),
    ("bitcoin", "requests Bitcoin"),
    ("crypto payment", "requests crypto payment"),
    ("bank details", "requests bank details"),
    ("send money", "asks for money"),
)
REVIEW_PHRASES: Tuple[Tuple[str, str], ...] = (
    ("telegram only", "only reachable through Telegram"),
    ("whatsapp only", "only reachable through WhatsApp"),
    ("dm me", "asks for a direct message instead of a business contact"),
    ("inbox me", "asks for a direct message instead of a business contact"),
    ("verify your account", "contains account-verification language"),
    ("click the link", "contains an unsolicited link instruction"),
    ("urgent payment", "pressures for urgent payment"),
)

# The owner's actual service catalogue (see README). A requirement only counts
# as matched when its recorded service fit names one of these capabilities.
SERVICE_KEYWORDS: Tuple[str, ...] = (
    "website", "web app", "web application", "landing page", "wordpress",
    "shopify", "ecommerce", "e-commerce", "frontend", "front-end", "backend",
    "back-end", "full stack", "full-stack", "android", "mobile app", "app development",
    "chatbot", "ai assistant", "ai tool", "automation", "workflow", "api integration",
    "integration", "excel", "spreadsheet", "data cleanup", "data cleaning",
    "data entry", "dashboard", "crm", "powerpoint", "word document", "pdf",
    "translation", "localization", "localisation", "telugu", "transcription",
    "subtitle", "caption", "proofreading", "content writing", "technical writing",
    "seo", "blog", "copywriting", "graphic design", "logo", "thumbnail",
    "banner", "ebook", "e-book", "prompt", "qa testing", "software testing",
    "bug report",
)

def _check(name: str, result: str, detail: str) -> Dict[str, str]:
    return {"check": name, "result": result, "detail": detail[:300]}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _host(value: Any) -> str:
    """Hostname for audit sources, never the full URL or an email address."""
    raw = _text(value)
    if not raw:
        return ""
    if "@" in raw and "://" not in raw:
        raw = raw.rsplit("@", 1)[-1]
    if "://" not in raw:
        raw = "//" + raw
    try:
        return (urlsplit(raw).hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return ""


def _is_ip_host(host: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host or ""))


def _on_free_site(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in FREE_SITE_SUFFIXES)


def _is_shortener(host: str) -> bool:
    return host in SHORTENER_DOMAINS


def _age_days(value: Any, now: datetime) -> Optional[float]:
    parsed = parse_iso(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 86400.0


def fingerprint(lead: Dict[str, Any]) -> str:
    """Hash of the facts verification depends on, to detect changed records."""
    parts = [
        _text(lead.get("company_name")).lower(),
        normalize_domain(lead.get("domain")),
        normalize_domain(lead.get("website")),
        normalize_email(lead.get("email")),
        _text(lead.get("email_status")).lower(),
        _text(lead.get("source_url")),
        _text(lead.get("need_summary"))[:400],
        _text(lead.get("service_fit")).lower(),
        _text(lead.get("notes"))[:400],
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def detect_fraud_indicators(lead: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return recorded fraud signals with their severity (``reject``/``review``).

    Only buyer-authored text is scanned, never the owner's own draft copy.
    """
    haystack = " ".join(
        _text(lead.get(field)).lower()
        for field in ("need_summary", "notes", "source_ref", "qualification_reason")
    )
    if not haystack.strip():
        return []
    indicators: List[Dict[str, str]] = []
    for phrase, label in HIGH_RISK_PHRASES:
        if phrase in haystack:
            indicators.append({"severity": "reject", "phrase": phrase, "detail": label})
    for phrase, label in REVIEW_PHRASES:
        if phrase in haystack:
            indicators.append({"severity": "review", "phrase": phrase, "detail": label})
    return indicators


def identity_assessment(lead: Dict[str, Any]) -> Tuple[str, str]:
    """Return (``matched``/``unconfirmed``/``mismatch``, owner-readable reason)."""
    website = normalize_domain(lead.get("website"))
    declared_domain = normalize_domain(lead.get("domain"))
    email = normalize_email(lead.get("email"))

    if not website:
        return IDENTITY_UNCONFIRMED, "No official website is recorded."
    host = _host(lead.get("website")) or website
    if _is_shortener(host):
        return IDENTITY_MISMATCH, "The website is a link shortener, not a business property."
    if _is_ip_host(host):
        return IDENTITY_UNCONFIRMED, "The website is a bare IP address with no business identity."
    if host.startswith("xn--") or ".xn--" in host:
        return IDENTITY_UNCONFIRMED, "Internationalised domain; identity needs a manual check."
    if _on_free_site(host):
        return IDENTITY_UNCONFIRMED, "The website sits on a shared free host, so the business identity is unconfirmed."
    if declared_domain and declared_domain != website:
        return IDENTITY_UNCONFIRMED, f"Recorded domain {declared_domain} disagrees with website {website}."

    if email:
        if is_disposable(email):
            return IDENTITY_MISMATCH, "The contact email uses a disposable mailbox."
        if email_matches_domain(email, website):
            return IDENTITY_MATCHED, f"Contact email belongs to {website}."
        if is_free_mail(email):
            return IDENTITY_UNCONFIRMED, "The contact email is a free mailbox, not a company address."
        return IDENTITY_UNCONFIRMED, "The contact email domain does not match the official website."
    return IDENTITY_MATCHED, f"Official website {website} recorded; no contact email to cross-check yet."


def requirement_assessment(lead: Dict[str, Any]) -> Tuple[bool, str]:
    evidence = requirement_evidence(lead)
    if not evidence:
        return False, "No source-linked business requirement is recorded; a company record alone is not a buying signal."
    source_host = _host(lead.get("source_url"))
    if _is_shortener(source_host):
        return False, "The requirement source is a link shortener, so the evidence cannot be reviewed."
    return True, "Source-linked requirement recorded."


def service_assessment(lead: Dict[str, Any]) -> Tuple[bool, str]:
    service = _text(lead.get("service_fit")).lower()
    if not service:
        return False, "No matched owner service is recorded."
    if not any(keyword in service for keyword in SERVICE_KEYWORDS):
        return False, "The recorded service fit does not match a service the owner can deliver."
    return True, f"Matched owner service: {service[:80]}."


def contact_assessment(lead: Dict[str, Any]) -> Tuple[bool, str]:
    email = normalize_email(lead.get("email"))
    if not email:
        return False, "No business email is recorded."
    if is_disposable(email):
        return False, "The business email is a disposable address."
    status = _text(lead.get("email_status")).lower()
    if status not in SENDABLE_EMAIL_STATUSES:
        return False, f"Email status '{status or 'unverified'}' has not been verified by the email provider."
    if not _text(lead.get("email_verified_at")):
        return False, "Email has no verification timestamp."
    return True, "Business email verified by the configured email verifier."


def _legal_basis(lead: Dict[str, Any], config: Any) -> str:
    if not normalize_email(lead.get("email")):
        return ""
    configured = _text(getattr(config, "outreach_legal_basis", "")) if config is not None else "legitimate_interest_b2b"
    return configured


def _sources(lead: Dict[str, Any]) -> str:
    parts: List[str] = []
    website = normalize_domain(lead.get("website"))
    if website:
        parts.append(f"website:{website}")
    requirement = _host(lead.get("source_url"))
    if requirement:
        parts.append(f"requirement:{requirement}")
    email_source = _text(lead.get("email_source"))
    if email_source:
        parts.append(f"email:{email_source}")
    provider = _text(lead.get("source_provider"))
    if provider:
        parts.append(f"discovered_by:{provider}")
    seen: List[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return "|".join(seen)[:500]


def assess_lead(
    lead: Dict[str, Any],
    config: Any = None,
    now: Optional[datetime] = None,
    max_age_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Assess one lead from recorded evidence. Pure: the input is not mutated.

    ``max_age_days`` is used only to mark an existing verification as due for
    recheck; the returned level itself never depends on wall-clock drift.
    """
    moment = now or now_utc()
    checks: List[Dict[str, str]] = []
    reject_reasons: List[str] = []
    hold_reasons: List[str] = []

    identity_status, identity_detail = identity_assessment(lead)
    checks.append(_check("identity", "pass" if identity_status == IDENTITY_MATCHED else ("reject" if identity_status == IDENTITY_MISMATCH else "hold"), identity_detail))
    if identity_status == IDENTITY_MISMATCH:
        reject_reasons.append(identity_detail)
    elif identity_status == IDENTITY_UNCONFIRMED:
        hold_reasons.append(identity_detail)

    indicators = detect_fraud_indicators(lead)
    severe = [indicator for indicator in indicators if indicator["severity"] == "reject"]
    review = [indicator for indicator in indicators if indicator["severity"] == "review"]
    if severe:
        checks.append(_check("fraud_screening", "reject", "; ".join(indicator["detail"] for indicator in severe)))
        reject_reasons.extend(indicator["detail"] for indicator in severe)
    elif review:
        checks.append(_check("fraud_screening", "hold", "; ".join(indicator["detail"] for indicator in review)))
        hold_reasons.extend(indicator["detail"] for indicator in review)
    else:
        checks.append(_check("fraud_screening", "pass", "No fraud-pattern phrases found in the recorded requirement."))

    requirement_ok, requirement_detail = requirement_assessment(lead)
    checks.append(_check("requirement", "pass" if requirement_ok else "hold", requirement_detail))
    if not requirement_ok:
        hold_reasons.append(requirement_detail)

    service_ok, service_detail = service_assessment(lead)
    checks.append(_check("service_match", "pass" if service_ok else "hold", service_detail))
    if not service_ok:
        hold_reasons.append(service_detail)

    contact_ok, contact_detail = contact_assessment(lead)
    checks.append(_check("contact", "pass" if contact_ok else "hold", contact_detail))
    if not contact_ok:
        hold_reasons.append(contact_detail)

    if _text(lead.get("do_not_contact")).lower() == "true" and contact_ok:
        checks.append(_check("suppression", "pass", "Lead is on the suppression list; outreach remains blocked by the separate gate."))

    if reject_reasons:
        status = VERIFICATION_REJECTED
        reason = "Rejected: " + "; ".join(reject_reasons)
    elif hold_reasons:
        status = VERIFICATION_PENDING
        reason = "Held for verification: " + "; ".join(hold_reasons)
    else:
        status = VERIFICATION_VERIFIED
        reason = "Verified genuine: identity matched, requirement sourced, service matched and contact verified."

    summary_reason = reason[:900]
    return {
        "status": status,
        "reason": summary_reason,
        "identity_status": identity_status,
        "method": VERIFICATION_METHOD,
        "sources": _sources(lead),
        "checks": checks,
        "fraud_indicators": [indicator["detail"] for indicator in indicators],
        "legal_basis": _legal_basis(lead, config),
        "checked_at": moment.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fingerprint": fingerprint(lead),
    }


def apply_verification(lead: Dict[str, Any], assessment: Dict[str, Any]) -> Dict[str, Any]:
    """Write an assessment onto a lead row (mutates and returns it)."""
    checked_at = _text(assessment.get("checked_at"))
    status = _text(assessment.get("status")) or VERIFICATION_PENDING
    lead["verification_status"] = status
    lead["verification_reason"] = _text(assessment.get("reason"))[:900]
    lead["identity_status"] = _text(assessment.get("identity_status")) or IDENTITY_UNCONFIRMED
    lead["verification_method"] = _text(assessment.get("method")) or VERIFICATION_METHOD
    lead["verification_sources"] = _text(assessment.get("sources"))[:500]
    lead["verification_checks"] = json.dumps(assessment.get("checks") or [], ensure_ascii=False)[:2000]
    lead["fraud_indicators"] = "|".join(assessment.get("fraud_indicators") or [])[:600]
    lead["legal_basis"] = _text(assessment.get("legal_basis"))[:120]
    lead["verification_checked_at"] = checked_at
    lead["verified_at"] = checked_at if status == VERIFICATION_VERIFIED else ""
    lead["verification_fingerprint"] = _text(assessment.get("fingerprint"))
    lead["updated_at"] = checked_at
    return lead


def needs_recheck(
    lead: Dict[str, Any],
    config: Any = None,
    now: Optional[datetime] = None,
) -> bool:
    """True when a lead must be assessed again before it can be contacted."""
    moment = now or now_utc()
    status = _text(lead.get("verification_status")).lower()
    if status != VERIFICATION_VERIFIED:
        return True
    if not _text(lead.get("verification_checked_at")):
        return True
    if _text(lead.get("verification_fingerprint")) != fingerprint(lead):
        return True
    max_age = int(getattr(config, "verification_max_age_days", 30) or 30)
    age = _age_days(lead.get("verification_checked_at"), moment)
    if age is None or age > max_age:
        return True
    if _text(lead.get("identity_status")) != IDENTITY_MATCHED:
        return True
    if _text(lead.get("fraud_indicators")):
        return True
    if _text(lead.get("email_status")).lower() not in SENDABLE_EMAIL_STATUSES:
        return True
    return False


def verification_gate(
    lead: Dict[str, Any],
    config: Any = None,
    now: Optional[datetime] = None,
) -> str:
    """Return a blocking reason, or ``""`` when the lead may be contacted.

    Called before qualification, before drafting and again before every send.
    """
    moment = now or now_utc()
    status = _text(lead.get("verification_status")).lower()
    if status != VERIFICATION_VERIFIED:
        return (
            "Lead is not in the verified-genuine category "
            f"(verification_status is '{status or 'unverified'}')."
        )
    if _text(lead.get("identity_status")) != IDENTITY_MATCHED:
        return "Lead identity is not confirmed as matching its website."
    if _text(lead.get("fraud_indicators")):
        return "Fraud screening flags are recorded for this lead: " + _text(lead.get("fraud_indicators"))[:200]
    if not _text(lead.get("verified_at")):
        return "Lead has no verification timestamp."
    if not requirement_evidence(lead):
        return "Lead no longer has source-linked requirement evidence."
    if not contact_assessment(lead)[0]:
        return "Lead contact is no longer verified: " + contact_assessment(lead)[1]
    if _text(lead.get("do_not_contact")).lower() == "true":
        return "Lead is marked do-not-contact."
    max_age = int(getattr(config, "verification_max_age_days", 30) or 30)
    age = _age_days(lead.get("verification_checked_at"), moment)
    if age is None:
        return "Lead has no readable verification timestamp."
    if age > max_age:
        return f"Verification is {age:.0f} days old (maximum {max_age}); run pipeline_verify.py before contacting."
    if config is not None and _text(getattr(config, "outreach_legal_basis", "")) and not _text(lead.get("legal_basis")):
        return "No legal basis is recorded for contacting this lead."
    return ""


def verification_summary(
    leads: Sequence[Dict[str, Any]],
    config: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Counts for the dashboard and reports. Unassessed rows are not 'verified'."""
    summary = {
        "total": len(leads),
        "verified_genuine": 0,
        "pending_verification": 0,
        "rejected_fraud": 0,
        "unassessed": 0,
        "recheck_due": 0,
    }
    for lead in leads:
        status = _text(lead.get("verification_status")).lower()
        if status in summary:
            summary[status] += 1
        elif not status:
            summary["unassessed"] += 1
        if status == VERIFICATION_VERIFIED and needs_recheck(lead, config, now):
            summary["recheck_due"] += 1
    return summary
