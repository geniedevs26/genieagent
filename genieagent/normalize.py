"""Normalisation and duplicate removal across company name, domain and email."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Tuple

LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "ltd", "limited", "plc", "corp", "corporation",
    "co", "company", "gmbh", "ag", "sa", "sas", "sarl", "srl", "bv", "nv", "oy", "ab",
    "as", "aps", "pty", "pte", "pvt", "private", "proprietary", "kk", "kg", "spa",
    "holdings", "holding", "group", "enterprises", "enterprise",
}

# Corporate descriptors are stripped only after legal suffixes, and only when a
# meaningful token would remain ("Acme Solutions" -> "acme").
DESCRIPTORS = {
    "solutions", "solution", "services", "service", "technologies", "technology",
    "tech", "systems", "system", "consulting", "consultants", "agency", "studio",
    "studios", "labs", "lab", "digital", "media", "global", "international", "online",
}

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")

FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in",
    "hotmail.com", "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com",
    "protonmail.com", "proton.me", "gmx.com", "mail.com", "zoho.com", "yandex.com",
}

DISPOSABLE_HINTS = ("tempmail", "throwaway", "mailinator", "guerrillamail", "10minutemail", "yopmail")

GENERIC_LOCAL_PARTS = {
    "info", "contact", "hello", "hi", "sales", "enquiries", "enquiry", "inquiries",
    "support", "office", "admin", "team", "business", "marketing", "help", "mail",
    "contactus", "general", "reception", "accounts", "billing", "partners",
}


def normalize_company(name: Any) -> str:
    """Lowercase, punctuation-free company key with legal/descriptor words removed."""
    text = str(name or "").lower()
    text = text.replace("&", " and ")
    text = PUNCT_RE.sub(" ", text)
    tokens = [token for token in SPACE_RE.sub(" ", text).strip().split(" ") if token]
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    while len(tokens) > 1 and tokens[-1] in DESCRIPTORS:
        tokens.pop()
    if tokens and tokens[0] in {"the"}:
        tokens = tokens[1:]
    return " ".join(tokens)


def normalize_domain(value: Any) -> str:
    """Return a bare lowercase host, stripping scheme, www, port and path."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "@" in raw and "://" not in raw:
        raw = raw.rsplit("@", 1)[-1]
    if "://" not in raw:
        raw = "//" + raw
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    if not host or "." not in host:
        return ""
    if host.endswith(".localhost") or host in {"localhost", "127.0.0.1"}:
        return ""
    return host


def normalize_email(value: Any) -> str:
    raw = str(value or "").strip().strip(".,;:<>()[]\"'").lower()
    if raw.startswith("mailto:"):
        raw = raw[7:].split("?", 1)[0]
    if raw.count("@") != 1:
        return ""
    local, domain = raw.split("@", 1)
    domain = normalize_domain(domain)
    if not local or not domain:
        return ""
    local = re.sub(r"\s+", "", local)
    return f"{local}@{domain}"


def is_free_mail(email: Any) -> bool:
    domain = str(email or "").split("@")[-1].lower()
    return domain in FREE_MAIL_DOMAINS


def is_disposable(email: Any) -> bool:
    domain = str(email or "").split("@")[-1].lower()
    return any(hint in domain for hint in DISPOSABLE_HINTS)


def is_generic_email(email: Any) -> bool:
    local = str(email or "").split("@")[0].lower()
    local = re.sub(r"[^a-z]", "", local)
    return local in GENERIC_LOCAL_PARTS or any(local.startswith(prefix) for prefix in ("info", "contact", "sales", "hello", "enquir"))


def email_matches_domain(email: Any, domain: Any) -> bool:
    """A business email should belong to the company domain (or a close subdomain)."""
    normalized = normalize_email(email)
    mail_domain = normalize_domain(normalized.split("@")[-1]) if normalized else ""
    company = normalize_domain(domain)
    if not mail_domain or not company:
        return False
    if mail_domain == company or mail_domain.endswith("." + company):
        return True
    # Reverse case: company domain is a subdomain of the email domain (mail.acme.com vs acme.com).
    return company.endswith("." + mail_domain)


def dedupe_key(lead: Dict[str, Any]) -> str:
    """Primary duplicate key: business domain, else normalised company + country."""
    domain = normalize_domain(lead.get("domain") or lead.get("website") or lead.get("source_url"))
    email = normalize_email(lead.get("email"))
    if email and "@" in email:
        mail_domain = normalize_domain(email.split("@")[-1])
        if mail_domain and mail_domain not in FREE_MAIL_DOMAINS:
            return "domain:" + mail_domain
    if domain:
        return "domain:" + domain
    company = normalize_company(lead.get("company_name"))
    if company:
        country = str(lead.get("country") or "").strip().lower()
        return f"company:{company}|{country}"
    return ""


def same_lead(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """True when two records describe the same business (name, domain or email)."""
    left_email = normalize_email(left.get("email"))
    right_email = normalize_email(right.get("email"))
    if left_email and right_email and left_email == right_email:
        return True
    left_domain = normalize_domain(left.get("domain") or left.get("website"))
    right_domain = normalize_domain(right.get("domain") or right.get("website"))
    if left_domain and right_domain and left_domain == right_domain:
        return True
    left_company = normalize_company(left.get("company_name"))
    right_company = normalize_company(right.get("company_name"))
    if left_company and right_company and left_company == right_company:
        left_country = str(left.get("country") or "").strip().lower()
        right_country = str(right.get("country") or "").strip().lower()
        if not left_country or not right_country or left_country == right_country:
            return True
    return False


# Field merge priority: higher tuple wins. Verified facts always beat guesses.
FIELD_PRIORITY: Dict[str, Tuple[str, ...]] = {
    "email_status": ("", "unverified", "unknown", "not_found", "accept_all", "valid", "deliverable"),
    "qualification_status": ("", "pending", "needs_review", "rejected", "qualified"),
    "outreach_status": (
        "", "not_contacted", "draft_pending_approval", "approved", "sent", "followed_up",
        "replied", "bounced", "opted_out", "closed",
    ),
    "order_status": (
        "", "none", "lost", "interested", "proposal_pending", "proposal_approved",
        "in_progress", "delivered", "closed",
    ),
}

FILL_ONLY_FIELDS = {
    "lead_id", "created_at", "source_provider", "source_url", "source_ref",
    "domain", "website", "company_name", "normalized_company", "country",
}

SCALAR_MAX_FIELDS = {
    "email_score": ("email_status", "qualification_score", "follow_up_count", "last_contact_at"),
    "qualification_score": ("email_score", "follow_up_count", "last_contact_at"),
    "follow_up_count": ("email_score", "qualification_score", "last_contact_at"),
    "last_contact_at": ("email_score", "qualification_score", "follow_up_count"),
    "last_reply_at": ("email_score", "qualification_score", "follow_up_count"),
}


def _numeric(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return -1.0


def _should_replace(field: str, current: Any, candidate: Any) -> bool:
    current_text = "" if current is None else str(current).strip()
    candidate_text = "" if candidate is None else str(candidate).strip()
    if not candidate_text:
        return False
    if not current_text:
        return True
    if field in FIELD_PRIORITY:
        order = FIELD_PRIORITY[field]
        current_rank = order.index(current_text.lower()) if current_text.lower() in order else -1
        candidate_rank = order.index(candidate_text.lower()) if candidate_text.lower() in order else -1
        return candidate_rank > current_rank
    if field in {"email_score", "qualification_score", "follow_up_count"}:
        return _numeric(candidate_text) > _numeric(current_text)
    if field in {"last_contact_at", "last_reply_at"}:
        return candidate_text > current_text  # ISO-8601 UTC sorts lexicographically
    return False


def merge_lead(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an incoming duplicate into an existing lead without losing evidence."""
    merged = dict(base)
    for key, value in incoming.items():
        if key in FILL_ONLY_FIELDS or key not in merged or not str(merged.get(key) or "").strip():
            if str(value or "").strip():
                merged[key] = value
            continue
        if _should_replace(key, merged.get(key), value):
            merged[key] = value
    merged["updated_at"] = max(str(base.get("updated_at") or ""), str(incoming.get("updated_at") or "")) or merged.get("updated_at", "")
    if not merged.get("created_at"):
        merged["created_at"] = merged.get("updated_at", "")
    return merged


def dedupe_leads(rows: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Collapse duplicate records; returns (unique rows, duplicates removed).

    Matching uses normalised domain, email and company name, in that order.
    """
    unique: List[Dict[str, Any]] = []
    removed = 0
    key_index: Dict[str, int] = {}
    for row in rows:
        candidate = dict(row)
        candidate["normalized_company"] = normalize_company(candidate.get("company_name"))
        candidate["domain"] = normalize_domain(candidate.get("domain") or candidate.get("website"))
        candidate["email"] = normalize_email(candidate.get("email"))
        candidate["dedupe_key"] = dedupe_key(candidate)
        key = candidate["dedupe_key"]
        if key and key in key_index:
            index = key_index[key]
            unique[index] = merge_lead(unique[index], candidate)
            unique[index]["dedupe_key"] = key
            removed += 1
            continue
        # Secondary scan catches the same business reached with a different key
        # (for example an Apollo company record and a Hunter email record).
        match_index = _find_match(unique, candidate)
        if match_index is not None:
            unique[match_index] = merge_lead(unique[match_index], candidate)
            merged_key = dedupe_key(unique[match_index])
            if merged_key:
                key_index[merged_key] = match_index
            removed += 1
            continue
        unique.append(candidate)
        if key:
            key_index[key] = len(unique) - 1
    return unique, removed


def _find_match(rows: List[Dict[str, Any]], candidate: Dict[str, Any]) -> int:
    candidate_email = normalize_email(candidate.get("email"))
    candidate_domain = normalize_domain(candidate.get("domain") or candidate.get("website"))
    candidate_company = normalize_company(candidate.get("company_name"))
    for index, existing in enumerate(rows):
        if candidate_email and candidate_email == normalize_email(existing.get("email")):
            return index
        existing_domain = normalize_domain(existing.get("domain") or existing.get("website"))
        if candidate_domain and existing_domain and candidate_domain == existing_domain:
            return index
        if candidate_company and candidate_company == normalize_company(existing.get("company_name")):
            candidate_country = str(candidate.get("country") or "").strip().lower()
            existing_country = str(existing.get("country") or "").strip().lower()
            if not candidate_country or not existing_country or candidate_country == existing_country:
                return index
    return None


def company_domain_from_url(url: Any) -> str:
    return normalize_domain(url)
