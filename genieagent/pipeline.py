"""Pipeline stages: discover -> enrich -> qualify -> draft -> sync -> send -> track -> report.

Every stage is idempotent and safe to re-run. No stage sends anything except
:func:`stage_send`, which requires a per-message owner approval and an explicit
``OUTREACH_SEND_ENABLED=true``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import Config
from .http import ProviderError, Transport
from .models import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_SUPPRESSED,
    LEAD_STATUS_NEEDS_REVIEW,
    LEAD_STATUS_QUALIFIED,
    OUTREACH_BOUNCED,
    OUTREACH_DRAFT_PENDING,
    OUTREACH_OPTED_OUT,
    OUTREACH_REPLIED,
    OUTREACH_SENT,
    ORDER_STATUSES,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
    VERIFICATION_VERIFIED,
)
from .normalize import normalize_company, normalize_domain, normalize_email
from .outreach.brevo import delivery_status_from_events, fetch_email_events, smtp_from_config
from .outreach.drafts import (
    _draft_row,
    approval_gate,
    plan_follow_up,
    prepare_drafts,
)
from .outreach.execute import apply_outcome, lead_after_send, send_draft
from .outreach.whatsapp import build_provider, provider_status
from .providers.apollo import client_from_config as apollo_client
from .providers.gemini import GeminiClient, validate_draft
from .providers.gemini import client_from_config as gemini_client
from .providers.hunter import client_from_config as hunter_client
from .qualify import (
    APOLLO_ONLY_NOTE,
    apply_qualification,
    email_is_contactable,
    qualification_gate,
    requirement_evidence,
)
from .storage.csv_store import activity_table, leads_table, outreach_table
from .sync import sync_all
from .util import mask_email, mask_phone, now_iso, read_csv, stable_id, write_json
from .verification import (
    apply_verification,
    assess_lead,
    verification_gate,
    verification_summary,
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
LONG_DIGITS_RE = re.compile(r"(?<![\w.])(\+?\d[\d\s().-]{6,}\d)(?![\w.])")
SECRETISH_RE = re.compile(r"\b(aiza|sk|pk|xoxb|ghp|glpat)[A-Za-z0-9_\-]{12,}\b")


def redact_pii(value: Any) -> str:
    """Remove emails, phone numbers and token-like strings from public output."""
    text = str(value or "")
    text = EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    text = LONG_DIGITS_RE.sub(lambda match: mask_phone(match.group(1)), text)
    text = SECRETISH_RE.sub("[redacted]", text)
    return text


# ------------------------------------------------------------------- plumbing


def _leads(config: Config):
    return leads_table(config.leads_csv)


def _drafts(config: Config):
    return outreach_table(config.outreach_csv)


def log(config: Config, event_type: str, status: str, summary: str, details: Any = "", lead_id: str = "") -> None:
    safe_details = details
    if isinstance(details, (dict, list)):
        safe_details = redact_pii(json.dumps(details, ensure_ascii=False))[:1500]
    else:
        safe_details = redact_pii(details)[:1500]
    activity_table(config.activity_csv).upsert(
        [
            {
                "event_id": stable_id(now_iso(), event_type, summary, lead_id),
                "timestamp": now_iso(),
                "event_type": event_type,
                "status": status,
                "lead_id": lead_id,
                "summary": redact_pii(summary)[:900],
                "details": safe_details,
            }
        ],
        touch=False,
    )


def _skipped(config: Config, stage: str, reason: str) -> Dict[str, Any]:
    log(config, f"{stage}_skipped", "skipped", reason)
    return {"stage": stage, "status": "skipped", "reason": reason}


def _push_lead(config: Config, lead: Dict[str, Any], transport: Optional[Transport] = None) -> bool:
    if not config.sheets_ready:
        return False
    from .storage.sheets import leads_sheet

    try:
        leads_sheet(config, transport=transport).upsert([lead])
        return True
    except Exception as exc:  # pragma: no cover - network dependent
        log(config, "sheets_push_failed", "failed", f"Lead push failed: {type(exc).__name__}", str(exc)[:300], lead.get("lead_id", ""))
        return False


def _push_draft(config: Config, draft: Dict[str, Any], transport: Optional[Transport] = None) -> bool:
    if not config.sheets_ready:
        return False
    from .storage.sheets import outreach_sheet

    try:
        outreach_sheet(config, transport=transport).upsert([draft])
        return True
    except Exception as exc:  # pragma: no cover - network dependent
        log(config, "sheets_push_failed", "failed", f"Draft push failed: {type(exc).__name__}", str(exc)[:300], draft.get("lead_id", ""))
        return False


def _limit(config: Config, override: Optional[int]) -> int:
    return max(1, int(override or config.max_leads_per_run))


# ------------------------------------------------------------------ discover


def stage_discover(
    config: Config,
    limit: Optional[int] = None,
    apollo: Optional[Any] = None,
    transport: Optional[Transport] = None,
) -> Dict[str, Any]:
    """Apollo company discovery for the configured ideal-customer profile."""
    if not config.apollo_ready and apollo is None:
        return _skipped(config, "discover", "APOLLO_API_KEY is not configured; Apollo discovery skipped.")
    if not config.apollo_keyword_tags:
        return _skipped(config, "discover", "APOLLO_KEYWORD_TAGS is empty; define target industries/services first.")
    client = apollo or apollo_client(config, transport=transport)
    table = _leads(config)
    existing = table.load()
    known_domains = {normalize_domain(row.get("domain") or row.get("website")) for row in existing}
    known_names = {normalize_company(row.get("company_name")) for row in existing}
    cap = _limit(config, limit)
    found: List[Dict[str, Any]] = []
    pages = 0
    for page in range(1, max(1, config.apollo_pages) + 1):
        if len(found) >= cap:
            break
        organizations = client.search_companies(
            keyword_tags=config.apollo_keyword_tags,
            locations=config.apollo_locations,
            employee_ranges=config.apollo_employee_ranges,
            page=page,
            per_page=config.apollo_per_page,
        )
        pages += 1
        if not organizations:
            break
        for organization in organizations:
            lead = client.company_to_lead(organization)
            if not lead:
                continue
            domain = normalize_domain(lead.get("domain"))
            name = normalize_company(lead.get("company_name"))
            if (domain and domain in known_domains) or (name and name in known_names):
                continue
            lead["notes"] = APOLLO_ONLY_NOTE + ": company data only, no stated business requirement yet."
            found.append(lead)
            if domain:
                known_domains.add(domain)
            if name:
                known_names.add(name)
            if len(found) >= cap:
                break
    result = table.upsert(found) if found else {"inserted": 0, "updated": 0, "unchanged": 0, "total": len(existing)}
    summary = {
        "stage": "discover",
        "status": "ok",
        "pages": pages,
        "found": len(found),
        "inserted": result.get("inserted", 0),
        "total_leads": result.get("total", 0),
    }
    log(config, "discover_completed", "ok", f"Apollo discovery: {len(found)} new companies", summary)
    if config.sheets_ready and found:
        from .storage.sheets import leads_sheet

        try:
            leads_sheet(config, transport=transport).upsert(found)
        except Exception as exc:  # pragma: no cover - network dependent
            log(config, "sheets_push_failed", "failed", "Lead sheet push failed", str(exc)[:300])
    return summary


# -------------------------------------------------------------------- import


def stage_import_candidates(
    config: Config,
    source: Optional[Path] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Import existing research rows (with stated buyer requirements) into leads.csv."""
    path = Path(source or Path("data/research_candidates.csv"))
    if not path.exists():
        return _skipped(config, "import", f"{path} does not exist yet.")
    rows = read_csv(path)
    if not rows:
        return _skipped(config, "import", f"{path} is empty.")
    imports: List[Dict[str, Any]] = []
    for row in rows[: _limit(config, limit) * 5]:
        company = str(row.get("company") or "").strip()
        website = str(row.get("website") or row.get("source") or "").strip()
        evidence = str(row.get("evidence") or "").strip()
        if not company or not evidence:
            continue
        source_url = str(row.get("needEvidenceUrl") or row.get("source") or website).strip()
        email = normalize_email(row.get("email"))
        timestamp = now_iso()
        domain = normalize_domain(website or source_url)
        imports.append(
            {
                "lead_id": stable_id("research", domain or company, str(row.get("country") or "")),
                "company_name": company[:200],
                "normalized_company": normalize_company(company),
                "domain": domain,
                "website": website,
                "country": str(row.get("country") or "").strip(),
                "industry": "",
                "employee_range": "",
                "contact_name": "",
                "contact_title": "",
                "email": email,
                "email_type": "",
                "email_status": "unverified",
                "email_score": "0",
                "email_verified_at": "",
                "email_source": "public_web_page" if email else "",
                "phone_business": str(row.get("phone") or "").strip(),
                "phone_source": str(row.get("phone_source") or "").strip(),
                "phone_type": "business" if row.get("phone") else "",
                "source_provider": "research_pipeline",
                "source_url": source_url,
                "source_ref": str(row.get("source") or ""),
                "service_fit": str(row.get("service") or "").strip(),
                "qualification_score": "0",
                "qualification_status": "pending",
                "qualification_reason": "",
                "need_summary": evidence[:400],
                "priority": "",
                "outreach_status": "not_contacted",
                "follow_up_count": "0",
                "last_contact_at": "",
                "last_reply_at": "",
                "order_status": "none",
                "whatsapp_status": "",
                "do_not_contact": "true" if str(row.get("status") or "") in {"Opted out", "Not interested"} else "false",
                "consent_basis": "",
                "notes": evidence[:1500],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
    result = _leads(config).upsert(imports)
    summary = {
        "stage": "import",
        "status": "ok",
        "source_rows": len(rows),
        "imported": len(imports),
        "inserted": result.get("inserted", 0),
        "total_leads": result.get("total", 0),
    }
    log(config, "import_completed", "ok", f"Imported {len(imports)} research rows into leads.csv", summary)
    if config.sheets_ready and imports:
        from .storage.sheets import leads_sheet

        try:
            leads_sheet(config).upsert(imports)
        except Exception as exc:  # pragma: no cover - network dependent
            log(config, "sheets_push_failed", "failed", "Lead sheet push failed", str(exc)[:300])
    return summary


# -------------------------------------------------------------------- enrich


def stage_enrich(
    config: Config,
    limit: Optional[int] = None,
    hunter: Optional[Any] = None,
    transport: Optional[Transport] = None,
    verify_only: bool = False,
) -> Dict[str, Any]:
    """Find and verify business emails through Hunter. Never guesses an address."""
    if not config.hunter_ready and hunter is None:
        return _skipped(config, "enrich", "HUNTER_API_KEY is not configured; email enrichment skipped.")
    client = hunter or hunter_client(config, transport=transport)
    table = _leads(config)
    rows = table.load()
    candidates = [
        row
        for row in rows
        if str(row.get("do_not_contact") or "").lower() != "true"
        and str(row.get("email_status") or "").lower() not in {"valid", "deliverable"}
        and normalize_domain(row.get("domain") or row.get("website"))
    ]
    updated: List[Dict[str, Any]] = []
    verified = not_found = failures = 0
    for row in candidates[: _limit(config, limit)]:
        domain = normalize_domain(row.get("domain") or row.get("website"))
        existing_email = normalize_email(row.get("email"))
        try:
            if existing_email:
                checked = client.verify_email(existing_email)
                status = str(checked.get("status") or "unknown").lower()
                row["email_status"] = "valid" if status in {"valid", "deliverable"} else (status or "unknown")
                row["email_score"] = str(checked.get("score") or row.get("email_score") or 0)
                row["email_verified_at"] = now_iso() if row["email_status"] == "valid" else ""
                row["email_source"] = "hunter_email_verifier"
                row["updated_at"] = now_iso()
                updated.append(row)
                if row["email_status"] == "valid":
                    verified += 1
                continue
            if verify_only:
                continue
            emails = client.domain_search(domain, limit=config.hunter_domain_limit)
            best = client.choose_business_email(domain, emails, verify=True)
            if best.get("email"):
                row["email"] = best["email"]
                row["email_type"] = best.get("email_type", "")
                row["email_status"] = best.get("email_status", "unknown")
                row["email_score"] = best.get("email_score", "0")
                row["email_verified_at"] = best.get("email_verified_at", "")
                row["email_source"] = best.get("email_source", "hunter_domain_search")
                if not row.get("contact_name") and best.get("contact_name"):
                    row["contact_name"] = best["contact_name"]
                if not row.get("contact_title") and best.get("contact_title"):
                    row["contact_title"] = best["contact_title"]
                if row["email_status"] in {"valid", "deliverable"}:
                    verified += 1
                updated.append(row)
            else:
                row["email_status"] = row.get("email_status") or "not_found"
                row["email_verified_at"] = ""
                not_found += 1
                row["updated_at"] = now_iso()
                updated.append(row)
        except ProviderError as exc:
            failures += 1
            log(config, "enrich_failed", "failed", f"Hunter lookup failed for one lead: {exc.provider}", str(exc)[:300], row.get("lead_id", ""))
            if failures >= 3:
                break
    if updated:
        table.upsert(updated)
        if config.sheets_ready:
            from .storage.sheets import leads_sheet

            try:
                leads_sheet(config, transport=transport).upsert(updated)
            except Exception as exc:  # pragma: no cover - network dependent
                log(config, "sheets_push_failed", "failed", "Lead sheet push failed", str(exc)[:300])
    summary = {
        "stage": "enrich",
        "status": "ok" if not failures else "partial",
        "checked": min(len(candidates), _limit(config, limit)),
        "verified": verified,
        "not_found": not_found,
        "failures": failures,
        "remaining": max(0, len(candidates) - _limit(config, limit)),
    }
    log(config, "enrich_completed", summary["status"], f"Hunter enrichment: {verified} verified emails", summary)
    return summary


# -------------------------------------------------------------------- verify


def stage_verify(
    config: Config,
    limit: Optional[int] = None,
    transport: Optional[Transport] = None,
) -> Dict[str, Any]:
    """Apply strict authenticity verification to recorded leads.

    Deterministic and offline: each decision is derived from stored evidence, and
    anything missing holds the lead instead of promoting it. Queued drafts for a
    lead that stops being verified are suppressed, never sent.
    """
    table = _leads(config)
    leads = table.load()
    if not leads:
        return _skipped(config, "verify", "No leads to verify yet.")
    drafts_table = _drafts(config)
    drafts = drafts_table.load()
    cap = max(1, int(limit or 500))
    assessed = 0
    transitions = 0
    suppressed = 0
    for lead in leads[:cap]:
        before_status = str(lead.get("verification_status") or "")
        assessment = assess_lead(lead, config)
        apply_verification(lead, assessment)
        assessed += 1
        after_status = str(lead.get("verification_status") or "")
        if after_status != before_status:
            transitions += 1
            if transitions <= 25:
                log(
                    config,
                    "verification_changed",
                    after_status,
                    f"Verification set to {after_status}",
                    {"previous": before_status or "unassessed", "reason": str(assessment.get("reason") or "")[:300]},
                    str(lead.get("lead_id") or ""),
                )
        # Suppression applies on every run, not only when the status changes: an
        # operator could otherwise approve a draft for a lead that was already
        # rejected before this stage ran.
        if after_status == VERIFICATION_VERIFIED:
            continue
        for draft in drafts:
            if str(draft.get("lead_id") or "") != str(lead.get("lead_id") or ""):
                continue
            if str(draft.get("approval_status") or "") not in {APPROVAL_PENDING, APPROVAL_APPROVED}:
                continue
            draft["approval_status"] = APPROVAL_SUPPRESSED
            draft["failure_reason"] = ("Verification: " + str(assessment.get("reason") or ""))[:500]
            draft["updated_at"] = now_iso()
            suppressed += 1
            log(
                config,
                "draft_suppressed",
                "blocked",
                "Queued draft suppressed because the lead is no longer verified",
                {"draft_id": draft.get("draft_id"), "verification_status": after_status},
                str(lead.get("lead_id") or ""),
            )
    table.upsert(leads[:cap])
    if suppressed:
        drafts_table.upsert(drafts)
    if config.sheets_ready:
        from .storage.sheets import leads_sheet

        try:
            leads_sheet(config, transport=transport).upsert(leads[:cap])
            if suppressed:
                from .storage.sheets import outreach_sheet

                outreach_sheet(config, transport=transport).upsert(drafts)
        except Exception as exc:  # pragma: no cover - network dependent
            log(config, "sheets_push_failed", "failed", "Verification push failed", str(exc)[:300])
    counts = verification_summary(leads[:cap], config)
    summary = {
        "stage": "verify",
        "status": "ok",
        "checked": assessed,
        "verified": counts["verified_genuine"],
        "pending": counts["pending_verification"],
        "rejected": counts["rejected_fraud"],
        "status_changes": transitions,
        "drafts_suppressed": suppressed,
        "message": "Only verified_genuine leads can be qualified, drafted or sent.",
    }
    log(config, "verify_completed", "ok", f"Verification checked {assessed} lead(s)", {k: v for k, v in summary.items() if k != "message"})
    return summary


# ------------------------------------------------------------------- qualify


def stage_qualify(
    config: Config,
    limit: Optional[int] = None,
    gemini: Optional[GeminiClient] = None,
    transport: Optional[Transport] = None,
) -> Dict[str, Any]:
    """Score leads with Gemini using only recorded, source-linked evidence."""
    if not config.gemini_ready and gemini is None:
        return _skipped(config, "qualify", "GEMINI_API_KEY is not configured; AI qualification skipped.")
    client = gemini or gemini_client(config, transport=transport)
    table = _leads(config)
    rows = table.load()
    eligible = [
        row
        for row in rows
        if str(row.get("qualification_status") or "pending") in {"", "pending", LEAD_STATUS_NEEDS_REVIEW}
        and str(row.get("do_not_contact") or "").lower() != "true"
    ]
    updated: List[Dict[str, Any]] = []
    qualified = rejected = blocked = blocked_unverified = failures = 0
    for row in eligible[: _limit(config, limit)]:
        verification_reason = verification_gate(row, config)
        if verification_reason:
            row["qualification_status"] = LEAD_STATUS_NEEDS_REVIEW
            row["qualification_reason"] = "Verification: " + verification_reason
            row["updated_at"] = now_iso()
            updated.append(row)
            blocked_unverified += 1
            continue
        reason = qualification_gate(row)
        if reason:
            row["qualification_status"] = LEAD_STATUS_NEEDS_REVIEW
            row["qualification_reason"] = reason
            row["updated_at"] = now_iso()
            updated.append(row)
            blocked += 1
            continue
        try:
            result = client.qualify_lead(row, min_score=config.outreach_min_score)
        except ProviderError as exc:
            failures += 1
            row["qualification_status"] = LEAD_STATUS_NEEDS_REVIEW
            row["qualification_reason"] = f"AI qualification failed: {exc.message[:200]}"
            row["updated_at"] = now_iso()
            updated.append(row)
            log(config, "qualify_failed", "failed", "Gemini qualification failed for one lead", str(exc)[:300], row.get("lead_id", ""))
            continue
        apply_qualification(row, result, min_score=config.outreach_min_score)
        row["updated_at"] = now_iso()
        updated.append(row)
        if row["qualification_status"] == LEAD_STATUS_QUALIFIED:
            qualified += 1
        else:
            rejected += 1
    if updated:
        table.upsert(updated)
        if config.sheets_ready:
            from .storage.sheets import leads_sheet

            try:
                leads_sheet(config, transport=transport).upsert(updated)
            except Exception as exc:  # pragma: no cover - network dependent
                log(config, "sheets_push_failed", "failed", "Lead sheet push failed", str(exc)[:300])
    summary = {
        "stage": "qualify",
        "status": "ok" if not failures else "partial",
        "evaluated": len(updated),
        "qualified": qualified,
        "rejected": rejected,
        "blocked_unverified": blocked_unverified,
        "blocked_without_evidence": blocked,
        "failures": failures,
    }
    log(config, "qualify_completed", summary["status"], f"Gemini qualification: {qualified} qualified", summary)
    return summary


# --------------------------------------------------------------------- draft


def stage_draft(
    config: Config,
    limit: Optional[int] = None,
    gemini: Optional[GeminiClient] = None,
    include_whatsapp: bool = True,
    followups: bool = False,
    transport: Optional[Transport] = None,
) -> Dict[str, Any]:
    """Generate personalized drafts and queue them as pending owner approval."""
    stage_name = "followups" if followups else "draft"
    if not config.gemini_ready and gemini is None:
        return _skipped(config, stage_name, "GEMINI_API_KEY is not configured; drafting skipped.")
    client = gemini or gemini_client(config, transport=transport)
    lead_table = _leads(config)
    draft_table = _drafts(config)
    leads = lead_table.load()
    drafts = draft_table.load()
    created: List[Dict[str, Any]] = []
    skipped_reasons: List[str] = []
    generated = failures = 0
    for lead in leads[: _limit(config, limit) * 3]:
        if len(created) >= _limit(config, limit):
            break
        if str(lead.get("qualification_status") or "") != LEAD_STATUS_QUALIFIED:
            continue
        if not email_is_contactable(lead):
            continue
        lead_drafts = [row for row in drafts if str(row.get("lead_id") or "") == str(lead.get("lead_id") or "")]
        if not followups and any(
            row.get("approval_status") in {APPROVAL_PENDING, APPROVAL_APPROVED}
            for row in lead_drafts
        ):
            continue
        try:
            if followups:
                due, previous_id, reason = plan_follow_up(lead, lead_drafts, config)
                if not due:
                    continue
                previous_subject = next(
                    (str(row.get("subject") or "") for row in lead_drafts if row.get("draft_id") == previous_id), ""
                )
                draft_payload = client.draft_follow_up(
                    lead, previous_subject=previous_subject, sender_name=config.owner_name, portfolio_url=config.portfolio_url
                )
                problems = validate_draft(draft_payload, portfolio_url=config.portfolio_url)
                if problems:
                    skipped_reasons.extend(problems)
                    continue
                row = _draft_row(
                    lead,
                    "email",
                    "brevo_smtp",
                    str(lead.get("email") or ""),
                    str(draft_payload.get("subject") or ""),
                    str(draft_payload.get("email_body") or ""),
                    now_iso(),
                    follow_up_of=previous_id,
                )
                created.append(row)
                generated += 1
                continue
            draft_payload = client.draft_outreach(
                lead, sender_name=config.owner_name, portfolio_url=config.portfolio_url
            )
        except ProviderError as exc:
            failures += 1
            log(config, "draft_failed", "failed", "Gemini draft failed for one lead", str(exc)[:300], lead.get("lead_id", ""))
            continue
        new_rows, reasons = prepare_drafts(
            lead, draft_payload, config, drafts, include_whatsapp=include_whatsapp
        )
        skipped_reasons.extend(reasons)
        for row in new_rows:
            created.append(row)
            drafts.append(row)
            generated += 1
        if new_rows:
            lead["outreach_status"] = OUTREACH_DRAFT_PENDING
            lead["updated_at"] = now_iso()
            lead_table.upsert([lead])
    if created:
        draft_table.upsert(created)
        if config.sheets_ready:
            from .storage.sheets import outreach_sheet

            try:
                outreach_sheet(config, transport=transport).upsert(created)
            except Exception as exc:  # pragma: no cover - network dependent
                log(config, "sheets_push_failed", "failed", "Draft sheet push failed", str(exc)[:300])
    summary = {
        "stage": stage_name,
        "status": "ok" if not failures else "partial",
        "drafts_created": len(created),
        "failures": failures,
        "held": len(skipped_reasons),
        "notes": skipped_reasons[:10],
        "message": "Drafts are pending owner approval; nothing was sent.",
    }
    log(config, f"{stage_name}_completed", summary["status"], f"{len(created)} drafts queued for approval", summary)
    return summary


# ---------------------------------------------------------------------- send


def stage_send(
    config: Config,
    limit: Optional[int] = None,
    unattended: bool = False,
    dry_run: Optional[bool] = None,
    smtp: Optional[Any] = None,
    whatsapp_provider: Optional[Any] = None,
    transport: Optional[Transport] = None,
) -> Dict[str, Any]:
    """Send only drafts with recorded owner approval, verified contacts and consent."""
    if not config.outreach_send_enabled:
        return _skipped(
            config,
            "send",
            "OUTREACH_SEND_ENABLED is false. Approved drafts stay queued; enable sending only when you intend to send.",
        )
    if unattended and not config.auto_outreach_enabled:
        return _skipped(config, "send", "AUTO_OUTREACH_ENABLED is false; unattended sending is disabled.")
    dry = config.dry_run if dry_run is None else dry_run
    lead_table = _leads(config)
    draft_table = _drafts(config)
    leads = {str(row.get("lead_id") or ""): row for row in lead_table.load()}
    drafts = draft_table.load()
    all_drafts = list(drafts)
    approved = [row for row in drafts if str(row.get("approval_status") or "") == APPROVAL_APPROVED]
    smtp_client = smtp or smtp_from_config(config)
    wa = whatsapp_provider
    sent = blocked = failed = 0
    results: List[Dict[str, Any]] = []
    for draft in approved[: _limit(config, limit)]:
        lead = leads.get(str(draft.get("lead_id") or ""))
        if not lead:
            draft["approval_status"] = APPROVAL_REJECTED
            draft["failure_reason"] = "Lead record is missing."
            failed += 1
            continue
        ok, reason = approval_gate(draft, lead, config, all_drafts, unattended=unattended)
        if not ok:
            blocked += 1
            draft["failure_reason"] = reason
            if any(word in reason.lower() for word in ("suppress", "do-not-contact", "opted out", "not verified", "matches the verified")):
                draft["approval_status"] = APPROVAL_SUPPRESSED
            draft["updated_at"] = now_iso()
            results.append({"draft_id": draft.get("draft_id"), "status": "blocked", "reason": reason})
            log(config, "send_blocked", "blocked", reason, {"draft_id": draft.get("draft_id")}, lead.get("lead_id", ""))
            continue
        try:
            attempt = int(float(str(draft.get("attempt_count") or 0))) + 1
        except ValueError:
            attempt = 1
        outcome = send_draft(draft, lead, config, smtp=smtp_client, whatsapp_provider=wa, dry_run=dry)
        if dry and outcome.ok:
            results.append({"draft_id": draft.get("draft_id"), "status": "dry_run", "detail": outcome.detail})
            continue
        apply_outcome(draft, outcome, attempt=attempt)
        if outcome.ok:
            sent += 1
            lead_after_send(lead, draft, status=OUTREACH_SENT)
            if draft.get("follow_up_of"):
                try:
                    lead["follow_up_count"] = str(int(float(str(lead.get("follow_up_count") or 0))) + 1)
                except ValueError:
                    lead["follow_up_count"] = "1"
            lead_table.upsert([lead])
            log(
                config,
                "outreach_sent",
                "ok",
                f"{draft.get('channel')} message accepted for one lead",
                {"draft_id": draft.get("draft_id"), "provider": draft.get("provider"), "delivery_status": draft.get("delivery_status")},
                lead.get("lead_id", ""),
            )
            results.append({"draft_id": draft.get("draft_id"), "status": "sent", "detail": outcome.detail})
        else:
            failed += 1
            log(
                config,
                "outreach_failed",
                "failed",
                f"{draft.get('channel')} send failed",
                {"draft_id": draft.get("draft_id"), "reason": outcome.detail},
                lead.get("lead_id", ""),
            )
            results.append({"draft_id": draft.get("draft_id"), "status": "failed", "detail": outcome.detail})
        draft["updated_at"] = now_iso()
        _push_lead(config, lead, transport=transport)
        _push_draft(config, draft, transport=transport)
    draft_table.upsert(drafts)
    summary = {
        "stage": "send",
        "status": "ok" if not failed else "partial",
        "approved_reviewed": min(len(approved), _limit(config, limit)),
        "sent": sent,
        "blocked": blocked,
        "failed": failed,
        "dry_run": dry,
        "results": results[:25],
        "message": "Only owner-approved messages were attempted. SMTP/API acceptance is not proof of delivery.",
    }
    log(config, "send_completed", summary["status"], summary["message"], {k: v for k, v in summary.items() if k != "results"})
    return summary


# --------------------------------------------------------------------- track


def mark_reply(config: Config, lead_id: str, note: str = "") -> Dict[str, Any]:
    table = _leads(config)
    lead = table.get(lead_id)
    if not lead:
        return {"status": "not_found", "lead_id": lead_id}
    lead["last_reply_at"] = now_iso()
    lead["outreach_status"] = OUTREACH_REPLIED
    lead["updated_at"] = now_iso()
    table.upsert([lead])
    log(config, "reply_recorded", "ok", "Owner recorded a client reply", note[:500], lead_id)
    _push_lead(config, lead)
    return {"status": "ok", "lead_id": lead_id, "outreach_status": OUTREACH_REPLIED}


def mark_opt_out(config: Config, lead_id: str, note: str = "") -> Dict[str, Any]:
    table = _leads(config)
    lead = table.get(lead_id)
    if not lead:
        return {"status": "not_found", "lead_id": lead_id}
    lead["do_not_contact"] = "true"
    lead["outreach_status"] = OUTREACH_OPTED_OUT
    lead["updated_at"] = now_iso()
    table.upsert([lead])
    log(config, "opt_out_recorded", "ok", "Opt-out recorded; future outreach suppressed", note[:500], lead_id)
    _push_lead(config, lead)
    return {"status": "ok", "lead_id": lead_id, "outreach_status": OUTREACH_OPTED_OUT}


def mark_order_status(config: Config, lead_id: str, order_status: str, note: str = "") -> Dict[str, Any]:
    if order_status not in ORDER_STATUSES:
        return {"status": "invalid", "reason": f"order_status must be one of {', '.join(ORDER_STATUSES)}"}
    table = _leads(config)
    lead = table.get(lead_id)
    if not lead:
        return {"status": "not_found", "lead_id": lead_id}
    lead["order_status"] = order_status
    lead["updated_at"] = now_iso()
    table.upsert([lead])
    log(config, "order_status_changed", "ok", f"Order status set to {order_status}", note[:500], lead_id)
    _push_lead(config, lead)
    return {"status": "ok", "lead_id": lead_id, "order_status": order_status}


def stage_track(config: Config, transport: Optional[Transport] = None, limit: int = 100) -> Dict[str, Any]:
    """Poll Brevo delivery events (when BREVO_API_KEY is set) and update statuses."""
    if not config.brevo_api_key:
        return _skipped(config, "track", "BREVO_API_KEY is not configured; delivery event tracking skipped.")
    draft_table = _drafts(config)
    lead_table = _leads(config)
    drafts = draft_table.load()
    leads = {str(row.get("lead_id") or ""): row for row in lead_table.load()}
    updated_drafts = 0
    bounced = delivered = 0
    for draft in drafts:
        if str(draft.get("channel") or "") != "email":
            continue
        if not str(draft.get("sent_at") or "").strip():
            continue
        if str(draft.get("delivery_status") or "") == "delivered":
            continue
        recipient = str(draft.get("recipient") or "")
        if not recipient:
            continue
        try:
            events = fetch_email_events(config.brevo_api_key, recipient, limit=20, transport=transport)
        except ProviderError as exc:
            log(config, "track_failed", "failed", "Brevo event lookup failed", str(exc)[:300], draft.get("lead_id", ""))
            break
        status = delivery_status_from_events(events)
        if not status or status == draft.get("delivery_status"):
            continue
        draft["delivery_status"] = status
        draft["updated_at"] = now_iso()
        updated_drafts += 1
        lead = leads.get(str(draft.get("lead_id") or ""))
        if status == "bounced":
            bounced += 1
            if lead:
                lead["outreach_status"] = OUTREACH_BOUNCED
                lead["email_status"] = "invalid"
                lead["do_not_contact"] = "true"
                lead["updated_at"] = now_iso()
                lead_table.upsert([lead])
                _push_lead(config, lead, transport=transport)
        elif status == "delivered":
            delivered += 1
        if updated_drafts >= limit:
            break
    if updated_drafts:
        draft_table.upsert(drafts)
        if config.sheets_ready:
            from .storage.sheets import outreach_sheet

            try:
                outreach_sheet(config, transport=transport).upsert(drafts)
            except Exception as exc:  # pragma: no cover - network dependent
                log(config, "sheets_push_failed", "failed", "Draft sheet push failed", str(exc)[:300])
    summary = {
        "stage": "track",
        "status": "ok",
        "updated": updated_drafts,
        "delivered": delivered,
        "bounced": bounced,
    }
    log(config, "track_completed", "ok", f"Delivery tracking updated {updated_drafts} draft(s)", summary)
    return summary


# --------------------------------------------------------------------- sync


def stage_sync(config: Config, direction: str = "both", transport: Optional[Transport] = None) -> Dict[str, Any]:
    if not config.sheets_ready:
        return _skipped(config, "sync", "Google Sheets is not configured; leads.csv remains the local source of truth.")
    report = sync_all(config, direction=direction, transport=transport)
    log(config, "sync_completed", "ok", f"Google Sheets sync ({direction}) complete", report)
    report["stage"] = "sync"
    report["status"] = "ok"
    return report


# ------------------------------------------------------------------- report


def build_dashboard(config: Config) -> Dict[str, Any]:
    """Build a privacy-safe dashboard payload (no full emails, no phone numbers)."""
    leads = _leads(config).load()
    drafts = _drafts(config).load()
    activity = activity_table(config.activity_csv).load()
    activity.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
    lead_by_id = {str(row.get("lead_id") or ""): row for row in leads}

    def count(field: str, value: str) -> int:
        return sum(1 for row in leads if str(row.get(field) or "") == value)

    # Only contacts on verified-genuine leads count as verified business emails.
    verified = sum(
        1
        for row in leads
        if email_is_contactable(row) and str(row.get("verification_status") or "") == VERIFICATION_VERIFIED
    )
    pending = sum(1 for row in drafts if str(row.get("approval_status")) == APPROVAL_PENDING)
    approved = sum(1 for row in drafts if str(row.get("approval_status")) == APPROVAL_APPROVED)
    sent = sum(1 for row in drafts if str(row.get("approval_status")) == "sent")
    failed = sum(1 for row in drafts if str(row.get("approval_status")) == "failed")
    opted_out = count("outreach_status", OUTREACH_OPTED_OUT)
    bounced = count("outreach_status", OUTREACH_BOUNCED)
    replied = count("outreach_status", OUTREACH_REPLIED)
    qualified = count("qualification_status", LEAD_STATUS_QUALIFIED)
    interested = count("order_status", "interested")
    sent_drafts = [draft for draft in drafts if str(draft.get("approval_status")) == "sent"]
    emails_sent = sum(1 for draft in sent_drafts if str(draft.get("channel")) == "email")
    whatsapp_sent = sum(1 for draft in sent_drafts if str(draft.get("channel")) == "whatsapp")
    verification = verification_summary(leads, config)

    countries: Dict[str, int] = {}
    services: Dict[str, int] = {}
    for row in leads:
        country = str(row.get("country") or "Unknown").strip() or "Unknown"
        countries[country] = countries.get(country, 0) + 1
        service = str(row.get("service_fit") or "Unclassified").strip() or "Unclassified"
        services[service] = services.get(service, 0) + 1

    public_leads = []
    for row in sorted(leads, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[:500]:
        public_leads.append(
            {
                "lead_id": row.get("lead_id", ""),
                "company": row.get("company_name", ""),
                "country": row.get("country", ""),
                "industry": row.get("industry", ""),
                "employees": row.get("employee_range", ""),
                "domain": row.get("domain", ""),
                "email_masked": mask_email(row.get("email")),
                "email_status": row.get("email_status", ""),
                "score": row.get("qualification_score", ""),
                "qualification_status": row.get("qualification_status", ""),
                "verification_status": row.get("verification_status", ""),
                "verification_reason": redact_pii(row.get("verification_reason"))[:300],
                "identity_status": row.get("identity_status", ""),
                "verification_sources": redact_pii(row.get("verification_sources"))[:240],
                "fraud_indicators": redact_pii(row.get("fraud_indicators"))[:240],
                "verification_checked_at": row.get("verification_checked_at", ""),
                "verified_at": row.get("verified_at", ""),
                "service_fit": row.get("service_fit", ""),
                "priority": row.get("priority", ""),
                "outreach_status": row.get("outreach_status", ""),
                "follow_up_count": row.get("follow_up_count", ""),
                "last_contact_at": row.get("last_contact_at", ""),
                "order_status": row.get("order_status", ""),
                "source_provider": row.get("source_provider", ""),
                "source_url": row.get("source_url", ""),
                "updated_at": row.get("updated_at", ""),
            }
        )

    public_drafts = []
    for draft in sorted(drafts, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[:300]:
        lead = lead_by_id.get(str(draft.get("lead_id") or ""), {})
        public_drafts.append(
            {
                "draft_id": draft.get("draft_id", ""),
                "company": lead.get("company_name", ""),
                "channel": draft.get("channel", ""),
                "provider": draft.get("provider", ""),
                "recipient_masked": draft.get("recipient_masked") or mask_email(draft.get("recipient")),
                "subject": redact_pii(draft.get("subject"))[:160],
                "approval_status": draft.get("approval_status", ""),
                "delivery_status": draft.get("delivery_status", ""),
                "created_at": draft.get("created_at", ""),
                "sent_at": draft.get("sent_at", ""),
                "failure_reason": redact_pii(draft.get("failure_reason"))[:200],
                "is_follow_up": bool(draft.get("follow_up_of")),
            }
        )

    public_activity = []
    for event in activity[:80]:
        public_activity.append(
            {
                "timestamp": event.get("timestamp", ""),
                "event_type": event.get("event_type", ""),
                "status": event.get("status", ""),
                "summary": redact_pii(event.get("summary"))[:240],
            }
        )

    recent_rejections = [
        {
            "company": redact_pii(row.get("company_name"))[:160],
            "reason": redact_pii(row.get("verification_reason"))[:260],
            "checked_at": row.get("verification_checked_at", ""),
            "sources": redact_pii(row.get("verification_sources"))[:200],
        }
        for row in leads
        if str(row.get("verification_status") or "") == VERIFICATION_REJECTED
    ][:10]
    recent_holds = [
        {
            "company": redact_pii(row.get("company_name"))[:160],
            "reason": redact_pii(row.get("verification_reason"))[:260],
            "checked_at": row.get("verification_checked_at", ""),
        }
        for row in leads
        if str(row.get("verification_status") or "") == VERIFICATION_PENDING
    ][:10]
    failures = [event for event in activity if str(event.get("status") or "") == "failed"][:5]

    return {
        "generated_at": now_iso(),
        "safety": {
            **config.safety_summary(),
            "whatsapp": provider_status(config) if config.whatsapp_provider != "none" else {"provider": "none", "configured": False},
            "banner": (
                "Automatic outreach is disabled. Only leads verified as genuine may be qualified, "
                "drafted or sent, and every message still requires per-message owner approval."
            ),
        },
        "settings": {
            "outreach_send_enabled": config.outreach_send_enabled,
            "whatsapp_send_enabled": config.whatsapp_send_enabled,
            "auto_outreach_enabled": config.auto_outreach_enabled,
            "owner_approval_required": True,
            "outreach_daily_limit": config.outreach_daily_limit,
            "outreach_min_score": config.outreach_min_score,
            "follow_up_days": list(config.outreach_followup_days),
            "verification_max_age_days": config.verification_max_age_days,
            "legal_basis": config.outreach_legal_basis,
            "suppressed_recipients": len(config.suppressed_emails),
        },
        "automation": {
            "last_event_at": activity[0].get("timestamp", "") if activity else "",
            "last_event_summary": redact_pii(activity[0].get("summary"))[:240] if activity else "",
            "recent_failures": [
                {
                    "timestamp": event.get("timestamp", ""),
                    "summary": redact_pii(event.get("summary"))[:220],
                }
                for event in failures
            ],
            "pending_drafts": pending,
            "approved_waiting": approved,
            "schedule": "GitHub Actions every 6 hours; manual or Termux scheduler otherwise",
            "sending_requires": "OUTREACH_SEND_ENABLED=true and a recorded owner approval per draft",
        },
        "verification": {**verification, "recent_rejections": recent_rejections, "recent_holds": recent_holds},
        "totals": {
            "leads": len(leads),
            "verified_emails": verified,
            "qualified": qualified,
            "drafts_pending_approval": pending,
            "drafts_approved": approved,
            "messages_sent": sent,
            "emails_sent": emails_sent,
            "whatsapp_sent": whatsapp_sent,
            "send_failures": failed,
            "replies": replied,
            "interested": interested,
            "bounces": bounced,
            "opt_outs": opted_out,
            "orders": sum(1 for row in leads if str(row.get("order_status") or "none") not in ("", "none")),
            "rejected": count("qualification_status", "rejected"),
            "needs_review": count("qualification_status", LEAD_STATUS_NEEDS_REVIEW),
            "verified_genuine": verification["verified_genuine"],
            "verification_pending": verification["pending_verification"],
            "rejected_fraud": verification["rejected_fraud"],
            "verification_recheck_due": verification["recheck_due"],
        },
        "orders": {status: count("order_status", status) for status in ORDER_STATUSES},
        "by_country": dict(sorted(countries.items(), key=lambda item: item[1], reverse=True)[:12]),
        "by_service": dict(sorted(services.items(), key=lambda item: item[1], reverse=True)[:12]),
        "leads": public_leads,
        "drafts": public_drafts,
        "activity": public_activity,
    }


def stage_report(config: Config, dashboard_path: Optional[Path] = None, transport: Optional[Transport] = None) -> Dict[str, Any]:
    payload = build_dashboard(config)
    write_json(Path(dashboard_path or config.dashboard_json), payload)
    totals = payload["totals"]
    summary = {
        "stage": "report",
        "status": "ok",
        "leads": totals["leads"],
        "verified_emails": totals["verified_emails"],
        "qualified": totals["qualified"],
        "pending_approval": totals["drafts_pending_approval"],
        "dashboard": str(dashboard_path or config.dashboard_json),
    }
    log(config, "report_completed", "ok", "Dashboard data exported", summary)
    return summary


# --------------------------------------------------------------- orchestration

STAGES: Dict[str, Callable[..., Dict[str, Any]]] = {
    "import": stage_import_candidates,
    "discover": stage_discover,
    "enrich": stage_enrich,
    "verify": stage_verify,
    "qualify": stage_qualify,
    "draft": stage_draft,
    "followups": stage_draft,
    "sync": stage_sync,
    "send": stage_send,
    "track": stage_track,
    "report": stage_report,
}


STAGE_PARAMS: Dict[str, set] = {
    "import": {"limit", "source"},
    "discover": {"limit", "apollo", "transport"},
    "enrich": {"limit", "hunter", "transport", "verify_only"},
    "verify": {"limit", "transport"},
    "qualify": {"limit", "gemini", "transport"},
    "draft": {"limit", "gemini", "include_whatsapp", "transport"},
    "followups": {"limit", "gemini", "include_whatsapp", "transport"},
    "sync": {"direction", "transport"},
    "send": {"limit", "unattended", "dry_run", "smtp", "whatsapp_provider", "transport"},
    "track": {"transport"},
    "report": {"dashboard_path", "transport"},
}


def run_stages(config: Config, stages: Sequence[str], **kwargs: Any) -> List[Dict[str, Any]]:
    """Run named stages in order, passing only the arguments each stage accepts."""
    results: List[Dict[str, Any]] = []
    for name in stages:
        stage = STAGES.get(name)
        if stage is None:
            results.append({"stage": name, "status": "unknown_stage"})
            continue
        allowed = STAGE_PARAMS.get(name, set())
        params = {key: value for key, value in kwargs.items() if key in allowed}
        if not params.get("source"):
            params.pop("source", None)
        if name == "followups":
            params.pop("include_whatsapp", None)
            results.append(stage(config, followups=True, include_whatsapp=False, **params))
        else:
            results.append(stage(config, **params))
    return results
